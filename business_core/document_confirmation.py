"""
Phase 16B.3: Human Confirmation of Structured Document Fields.

AI-derived structured fields (business_core.document_intelligence.
StructuredDocumentFields, Phase 16B.2) cannot be automatically treated
as confirmed business data — the same production PDF analyzed twice
(DREG-004/DREG-005, exact duplicates) produced a different direction,
different document_type, and different extracted representative
name/IIN. This module adds a field-level human confirmation layer on
top, WITHOUT letting confirmation automatically change any other
entity.

Architecture (per the approved 16B.3 audit):
  - DOCUMENT_FIELD_REVIEWS (business_core/sheets.py) is the append-only
    SOURCE OF TRUTH — every confirm/reject/clear decision is one
    immutable row there, never edited or deleted.
  - DOCUMENT_CONTENT's "Confirmed Fields JSON"/"Structured Review
    Status"/"Structured Review Version"/"Structured Review Updated At"
    columns are a materialized CURRENT-STATE CACHE, derivable from the
    append-only log — kept only so Telegram reads stay O(1) instead of
    scanning the whole review log every time.
  - Document-level (not per-field) optimistic concurrency: every
    mutation requires expected_version; a mismatch is a hard CONFLICT,
    zero writes, never last-write-wins.

Invariants (never violated by this module):
  - Never writes DOCUMENT_REGISTRY, Document Template ID, Document
    Status, Document Family/Version, STAGE_ENTITY_RELATIONS, or
    anything the Completion Gate reads.
  - Never changes business_core.document_intelligence's exact-duplicate
    canonical-selection algorithm, and never copies one document's
    confirmations to another (even an exact duplicate) — each Document
    ID's review state is fully independent.
  - Business ID is always derived from the document's own
    DOCUMENT_REGISTRY row — never accepted from caller input, matching
    the boundary pattern already used by
    business_core.business_builder._transition_commercial_offer().
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Phase 16B.3 §6: whitelist-only — arbitrary field names are rejected
# outright, never accepted "as long as they look plausible".
ALLOWED_STRUCTURED_FIELDS = (
    "document_number", "document_date", "issued_by",
    "valid_from", "valid_until", "has_expiration",
    "direction", "requires_action",
)

# Maps an allowed field name to its AI-derived DOCUMENT_CONTENT column
# (Phase 16B.2) — the ONLY thing ever read from that column here.
_AI_COLUMN_BY_FIELD = {
    "document_number": "Document Number",
    "document_date": "Document Date",
    "issued_by": "Issued By",
    "valid_from": "Valid From",
    "valid_until": "Valid Until",
    "has_expiration": "Has Expiration",
    "direction": "Direction",
    "requires_action": "Requires Action",
}

DECISION_CONFIRM = "confirm"
DECISION_REJECT = "reject"
DECISION_CLEAR = "clear"

STATUS_UNREVIEWED = "unreviewed"
STATUS_PARTIALLY_CONFIRMED = "partially_confirmed"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"

MAX_CONFIRMED_VALUE_CHARS = 300
MAX_ACTOR_CHARS = 100

# Google Sheets treats a cell starting with one of these as a formula —
# reject outright rather than silently prefixing/escaping (Phase 16B.3
# §16, scenario 20: command injection via value).
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@")


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _has_control_characters(text: str) -> bool:
    return any(ord(ch) < 32 and ch not in ("\t",) for ch in text)


def _validate_field_value(field: str, raw_value: str) -> tuple[str, str | None]:
    """Returns (normalized_value, error_message). error_message is None
    on success. Never raises."""
    from business_core.document_intelligence import parse_exact_date, DIRECTION_VALUES

    value = (raw_value or "").strip()

    if not value:
        return "", "Значение не может быть пустым."
    if _has_control_characters(value):
        return "", "Значение содержит недопустимые control-символы."
    if value[0] in _FORMULA_TRIGGER_CHARS:
        return "", "Значение не может начинаться с '=', '+', '-' или '@'."

    if field == "document_number":
        return value[:MAX_CONFIRMED_VALUE_CHARS], None

    if field in ("document_date", "valid_from", "valid_until"):
        iso, _warn = parse_exact_date(value)
        if not iso:
            return "", (
                f"Невалидная дата: {value!r}. Нужен точный формат "
                "YYYY-MM-DD (месяц/год без дня не подходит)."
            )
        return iso, None

    if field == "issued_by":
        return value[:MAX_CONFIRMED_VALUE_CHARS], None

    if field == "direction":
        v = value.lower()
        if v not in DIRECTION_VALUES:
            return "", f"direction должен быть одним из: {', '.join(DIRECTION_VALUES)}."
        return v, None

    if field in ("has_expiration", "requires_action"):
        v = value.lower()
        if v in ("true", "1"):
            return "true", None
        if v in ("false", "0"):
            return "false", None
        return "", "Значение должно быть true или false."

    return "", f"Поле '{field}' не разрешено для подтверждения."


def parse_confirmed_fields_json(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def parse_review_version(raw: str) -> int:
    text = (raw or "").strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def compute_aggregate_status(confirmed_fields: dict) -> str:
    """Phase 16B.3 §5. An AI value being "unknown" is NEVER
    automatically counted as reviewed — only an explicit confirm/reject
    decision counts."""
    decided = [
        entry.get("status")
        for field in ALLOWED_STRUCTURED_FIELDS
        for entry in (confirmed_fields.get(field),)
        if isinstance(entry, dict) and entry.get("status") in (STATUS_CONFIRMED, STATUS_REJECTED)
    ]
    if not decided:
        return STATUS_UNREVIEWED
    if STATUS_REJECTED in decided:
        return STATUS_REJECTED
    if len(decided) == len(ALLOWED_STRUCTURED_FIELDS):
        return STATUS_CONFIRMED
    return STATUS_PARTIALLY_CONFIRMED


def compute_effective_fields(content_row: dict, confirmed_fields: dict) -> dict:
    """Read-only, display-only. Returns
    {field: {"effective_value", "source" ("confirmed"|"ai"|"none"),
     "conflict", "ai_value", "review_field_status"}}.

    "conflict" is computed HERE, at read time, by comparing the stored
    confirmed value against the CURRENT AI-derived column — never
    persisted, so a reanalysis (business_core.document_intelligence.
    analyze_document, which never touches these 4 columns at all) is
    automatically reflected on the next read with no extra write.
    Effective value is for DISPLAY ONLY in this phase — never fed back
    into DOCUMENT_REGISTRY/Template ID/Status/Stage/Completion Gate/
    relations."""
    result = {}
    for field, col in _AI_COLUMN_BY_FIELD.items():
        ai_value = content_row.get(col, "") or ""
        entry = confirmed_fields.get(field)
        if isinstance(entry, dict) and entry.get("status") == STATUS_CONFIRMED:
            confirmed_value = entry.get("value", "") or ""
            result[field] = {
                "effective_value": confirmed_value,
                "source": "confirmed",
                "conflict": confirmed_value != ai_value,
                "ai_value": ai_value,
                "review_field_status": STATUS_CONFIRMED,
            }
        elif isinstance(entry, dict) and entry.get("status") == STATUS_REJECTED:
            result[field] = {
                "effective_value": "",
                "source": "none",
                "conflict": False,
                "ai_value": ai_value,
                "review_field_status": STATUS_REJECTED,
            }
        else:
            result[field] = {
                "effective_value": ai_value,
                "source": "ai",
                "conflict": False,
                "ai_value": ai_value,
                "review_field_status": STATUS_UNREVIEWED,
            }
    return result


def compute_mutation_id(document_id: str, field: str, decision: str, value: str, expected_version: int) -> str:
    """Deterministic idempotency key — a byte-identical retry (same
    Telegram command resent, e.g. after a dropped response) always
    computes the SAME Mutation ID, letting _apply_field_decision()
    recognize and safely no-op a replay instead of appending a second
    audit row. NEVER a freshly-generated ID per call (that would defeat
    idempotency entirely — see Phase 16B.3 §3)."""
    payload = f"{document_id}|{field}|{decision}|{value}|{expected_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def rebuild_confirmed_fields_from_reviews(reviews: list) -> dict:
    """
    Pure function — the cache-recovery/verification primitive. Given
    ALL DOCUMENT_FIELD_REVIEWS rows for ONE Document ID (any order),
    replays confirm/reject/clear in Review Version order and returns
    the materialized-cache shape that DOCUMENT_CONTENT's 4 review
    columns should hold:

        {"confirmed_fields": dict, "review_status": str,
         "review_version": int, "updated_at": str,
         "duplicate_versions": list[int]}

    duplicate_versions: Review Versions claimed by more than one row
    for this document — a genuine race (two concurrent mutations both
    read the same "current" version before either wrote) that Google
    Sheets' API offers no atomic compare-and-swap to fully prevent at
    write time. This function can only DETECT it, never silently hide
    it: the first-seen (by input order) row for a duplicated version
    wins deterministically, and the version is still reported so a
    caller can surface/investigate it.
    """
    def _v(r):
        try:
            return int(r.get("Review Version", "") or 0)
        except ValueError:
            return 0

    ordered = sorted(reviews, key=_v)
    seen_versions: dict = {}
    duplicate_versions: list = []
    confirmed: dict = {}
    updated_at = ""
    max_version = 0

    for r in ordered:
        v = _v(r)
        if v in seen_versions:
            duplicate_versions.append(v)
            continue
        seen_versions[v] = r

        field = r.get("Field Name", "")
        decision = r.get("Decision", "")
        if field not in ALLOWED_STRUCTURED_FIELDS:
            continue

        if decision == DECISION_CLEAR:
            confirmed.pop(field, None)
        elif decision in (DECISION_CONFIRM, DECISION_REJECT):
            confirmed[field] = {
                "value": r.get("Confirmed Value", "") if decision == DECISION_CONFIRM else "",
                "status": STATUS_CONFIRMED if decision == DECISION_CONFIRM else STATUS_REJECTED,
                "confirmed_by": r.get("Actor", ""),
                "confirmed_at": r.get("Reviewed At", ""),
                "version": v,
                "source_analysis_completed_at": r.get("Source Analysis Completed At", ""),
            }

        if r.get("Reviewed At"):
            updated_at = r["Reviewed At"]
        max_version = max(max_version, v)

    return {
        "confirmed_fields": confirmed,
        "review_status": compute_aggregate_status(confirmed),
        "review_version": max_version,
        "updated_at": updated_at,
        "duplicate_versions": duplicate_versions,
    }


def _reviews_sheet_ready() -> tuple[bool, str | None]:
    """Fail-closed readiness check — DOCUMENT_FIELD_REVIEWS must
    already exist with the exact canonical headers via a controlled
    admin migration (migrate_document_field_reviews.py). A Telegram
    mutation NEVER auto-provisions this sheet, unlike the default
    get_business_sheet() behavior (Phase 16B.3 §5)."""
    from business_core.sheets import business_sheet_exists, get_business_sheet, BUSINESS_HEADERS, read_with_retry

    if not business_sheet_exists("document_field_reviews"):
        return False, (
            "DOCUMENT_FIELD_REVIEWS ещё не создан. Требуется отдельная "
            "миграция: migrate_document_field_reviews.py --live"
        )
    headers = read_with_retry(get_business_sheet("document_field_reviews").row_values, 1)
    canonical = BUSINESS_HEADERS["document_field_reviews"]
    if headers != canonical:
        return False, (
            "DOCUMENT_FIELD_REVIEWS существует, но заголовки не совпадают с "
            "канонической схемой — требуется ручная проверка."
        )
    return True, None


def _find_existing_mutation(document_id: str, mutation_id: str) -> dict | None:
    """Idempotency lookup — read-only full-table scan of
    DOCUMENT_FIELD_REVIEWS (this table is small and append-only; no
    per-Document-ID index exists). Returns the matching row, or None."""
    from business_core.sheets import read_business_sheet

    for row in read_business_sheet("document_field_reviews"):
        if row.get("Document ID") == document_id and row.get("Mutation ID") == mutation_id:
            return row
    return None


def get_review_state(document_id: str) -> dict:
    """Read-only. Returns {"found": False} or {"found": True,
    "row": dict, "review_status": str, "review_version": int,
    "confirmed_fields": dict, "updated_at": str, "effective_fields": dict}."""
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("document_content", document_id)
    if not found:
        return {"found": False}
    _, row = found

    confirmed_fields = parse_confirmed_fields_json(row.get("Confirmed Fields JSON", ""))
    review_version = parse_review_version(row.get("Structured Review Version", ""))
    review_status = row.get("Structured Review Status", "") or STATUS_UNREVIEWED

    return {
        "found": True,
        "row": row,
        "review_status": review_status,
        "review_version": review_version,
        "confirmed_fields": confirmed_fields,
        "updated_at": row.get("Structured Review Updated At", "") or "",
        "effective_fields": compute_effective_fields(row, confirmed_fields),
    }


def _apply_field_decision(
    document_id: str, field: str, decision: str, value: str,
    actor: str, expected_version: int,
) -> dict:
    """Shared mutation engine for confirm/reject/clear.

    Write order (Phase 16B.3 rework — audit-first, per the corrected
    contract; the ORIGINAL cache-first order was a real atomicity gap,
    see the incident write-up):
      1. field whitelist / actor / (value already validated by caller).
      2. Reviews-sheet readiness — fail closed, never auto-provisions.
      3. Read DOCUMENT_CONTENT (current version, AI value, cache).
      4. Compute deterministic Mutation ID from the full payload
         (INCLUDING the client-supplied expected_version) and look it
         up FIRST, before any version check — a byte-identical retry
         after a successful-but-unacknowledged first attempt must
         return the SAME result, never a spurious VERSION_CONFLICT or
         a second audit row.
      5. Only if no existing Mutation ID match: check expected_version
         against the current cache version — mismatch is a hard
         CONFLICT, zero writes.
      6. Re-read the DOCUMENT_CONTENT version once more, immediately
         before the write, to narrow (never fully close — Sheets has
         no atomic compare-and-swap) the race window.
      7. Append the audit row — the FIRST write, and the only one that
         defines whether this mutation "happened". If this fails,
         NOTHING is written anywhere (code=AUDIT_APPEND_FAILED).
      8. Only after a successful append: rebuild the materialized cache
         from ALL of this Document ID's review rows (never incrementally
         patched in memory) and write it to DOCUMENT_CONTENT — the
         SECOND write. If this fails, the audit row (source of truth)
         already exists; this is reported as CACHE_SYNC_FAILED, never
         as an ordinary success — the next /reviewdoc recomputes the
         cache fresh from the same rebuild function, so the stale cache
         self-heals on the very next read rather than needing a
         separate repair command.

    Known limitation (disclosed, not silently hidden): two concurrent
    mutations on the same Document ID can both pass step 5 before
    either appends — the Sheets API offers no server-side conditional
    write to fully prevent this. rebuild_confirmed_fields_from_reviews()
    DETECTS a resulting duplicate Review Version (duplicate_versions)
    but cannot retroactively prevent it.

    Returns:
        {"ok": bool, "code": str, "error": str | None,
         "review_status": str | None, "review_version": int | None,
         "confirmed_fields": dict | None}
    """
    from business_core.sheets import (
        find_row_by_id, update_business_row, append_business_row,
        row_from_header_map, get_business_sheet, generate_next_id,
        read_business_sheet, read_with_retry,
        SheetsQuotaExceededError, TransientSheetsReadError,
    )

    if field not in ALLOWED_STRUCTURED_FIELDS:
        return {"ok": False, "code": "FIELD_NOT_ALLOWED",
                "error": f"Поле '{field}' не разрешено для подтверждения."}

    actor = (actor or "").strip()[:MAX_ACTOR_CHARS]
    if not actor:
        return {"ok": False, "code": "ACTOR_REQUIRED", "error": "Не удалось определить пользователя."}

    ready, ready_error = _reviews_sheet_ready()
    if not ready:
        return {"ok": False, "code": "REVIEWS_SHEET_NOT_READY", "error": ready_error}

    try:
        found = find_row_by_id("document_content", document_id)
    except (SheetsQuotaExceededError, TransientSheetsReadError) as exc:
        return {"ok": False, "code": "TRANSIENT_READ_ERROR", "error": str(exc)}

    if not found:
        return {"ok": False, "code": "DOCUMENT_NOT_FOUND",
                "error": f"DOCUMENT_CONTENT-запись {document_id} не найдена."}
    row_num, row = found

    ai_value = row.get(_AI_COLUMN_BY_FIELD[field], "") or ""
    source_completed_at = row.get("Analysis Completed At", "") or ""

    # Step 4: idempotency check FIRST — uses the CLIENT-SUPPLIED
    # expected_version (not the current one), so a retry of an already-
    # applied mutation is recognized even after the version has since
    # moved on.
    mutation_id = compute_mutation_id(document_id, field, decision, value, expected_version)
    try:
        existing = _find_existing_mutation(document_id, mutation_id)
    except (SheetsQuotaExceededError, TransientSheetsReadError) as exc:
        return {"ok": False, "code": "TRANSIENT_READ_ERROR", "error": str(exc)}

    if existing is not None:
        replayed_version = parse_review_version(existing.get("Review Version", ""))
        # Rebuild the authoritative cache state for the response — never
        # trust an incrementally-mutated in-memory dict for a replay.
        try:
            all_reviews = read_business_sheet("document_field_reviews")
        except Exception:
            all_reviews = [existing]
        doc_reviews = [r for r in all_reviews if r.get("Document ID") == document_id]
        rebuilt = rebuild_confirmed_fields_from_reviews(doc_reviews)
        return {
            "ok": True, "code": "OK_IDEMPOTENT_REPLAY", "error": None,
            "review_status": rebuilt["review_status"], "review_version": replayed_version,
            "confirmed_fields": rebuilt["confirmed_fields"],
        }

    # Step 5: version check (only reached if this exact mutation was
    # never applied before).
    current_version = parse_review_version(row.get("Structured Review Version", ""))
    if expected_version != current_version:
        return {
            "ok": False, "code": "VERSION_CONFLICT",
            "error": f"Версия устарела: ожидалась {expected_version}, актуальная {current_version}.",
            "review_version": current_version,
            "confirmed_fields": parse_confirmed_fields_json(row.get("Confirmed Fields JSON", "")),
        }

    # Step 6: re-check immediately before the write — narrows (does not
    # eliminate) the race window.
    try:
        recheck_found = find_row_by_id("document_content", document_id)
    except (SheetsQuotaExceededError, TransientSheetsReadError) as exc:
        return {"ok": False, "code": "TRANSIENT_READ_ERROR", "error": str(exc)}
    if not recheck_found:
        return {"ok": False, "code": "DOCUMENT_NOT_FOUND",
                "error": f"DOCUMENT_CONTENT-запись {document_id} не найдена."}
    _, recheck_row = recheck_found
    recheck_version = parse_review_version(recheck_row.get("Structured Review Version", ""))
    if recheck_version != expected_version:
        return {
            "ok": False, "code": "VERSION_CONFLICT",
            "error": f"Версия устарела: ожидалась {expected_version}, актуальная {recheck_version}.",
            "review_version": recheck_version,
            "confirmed_fields": parse_confirmed_fields_json(recheck_row.get("Confirmed Fields JSON", "")),
        }

    now = _now_utc_str()
    new_version = current_version + 1
    audit_confirmed_value = value if decision == DECISION_CONFIRM else ""

    # Business ID: derived from the document's OWN DOCUMENT_REGISTRY
    # row — never accepted from caller input (same boundary pattern as
    # the rest of Business Core).
    business_id = ""
    try:
        doc_found = find_row_by_id("document_registry", document_id)
        if doc_found:
            business_id = doc_found[1].get("Business ID", "") or ""
    except Exception:
        pass  # best-effort only for the audit row's Business ID column

    # Step 7: append the audit row — FIRST write, source of truth.
    try:
        review_id = generate_next_id("document_field_reviews")
        headers = read_with_retry(get_business_sheet("document_field_reviews").row_values, 1)
        audit_row = row_from_header_map(headers, {
            "Review ID": review_id,
            "Mutation ID": mutation_id,
            "Document ID": document_id,
            "Business ID": business_id,
            "Field Name": field,
            "AI Value": ai_value,
            "Confirmed Value": audit_confirmed_value,
            "Decision": decision,
            "Actor": actor,
            "Reviewed At": now,
            "Review Version": str(new_version),
            "Source Analysis Completed At": source_completed_at,
        })
        append_business_row("document_field_reviews", audit_row)
    except Exception as exc:
        log.error(f"_apply_field_decision({document_id}, {field}): audit append failed: {exc}")
        return {
            "ok": False, "code": "AUDIT_APPEND_FAILED",
            "error": "Решение НЕ сохранено — запись в аудит не удалась. Ничего не изменилось.",
        }

    # Step 8: rebuild the cache from ALL reviews (never an incremental
    # in-memory patch) and write it — SECOND write.
    try:
        all_reviews = read_business_sheet("document_field_reviews")
    except Exception as exc:
        log.error(f"_apply_field_decision({document_id}, {field}): post-append re-read failed: {exc}")
        return {
            "ok": False, "code": "CACHE_SYNC_FAILED",
            "error": (
                "Решение записано в аудит, но кэш не обновлён. Аудит — источник "
                "истины; повторите /reviewdoc, кэш пересчитается автоматически."
            ),
            "review_version": new_version,
        }
    doc_reviews = [r for r in all_reviews if r.get("Document ID") == document_id]
    rebuilt = rebuild_confirmed_fields_from_reviews(doc_reviews)

    try:
        update_business_row("document_content", row_num, {
            "Structured Review Status": rebuilt["review_status"],
            "Confirmed Fields JSON": json.dumps(rebuilt["confirmed_fields"], ensure_ascii=False, sort_keys=True),
            "Structured Review Version": str(rebuilt["review_version"]),
            "Structured Review Updated At": now,
        })
    except Exception as exc:
        log.error(f"_apply_field_decision({document_id}, {field}): cache write failed: {exc}")
        return {
            "ok": False, "code": "CACHE_SYNC_FAILED",
            "error": (
                "Решение записано в аудит, но кэш не обновлён. Аудит — источник "
                "истины; повторите /reviewdoc, кэш пересчитается автоматически."
            ),
            "review_version": rebuilt["review_version"],
            "confirmed_fields": rebuilt["confirmed_fields"],
        }

    return {
        "ok": True, "code": "OK", "error": None,
        "review_status": rebuilt["review_status"], "review_version": rebuilt["review_version"],
        "confirmed_fields": rebuilt["confirmed_fields"],
    }


def confirm_field(document_id: str, field: str, value: str, actor: str, expected_version: int) -> dict:
    if field not in ALLOWED_STRUCTURED_FIELDS:
        return {"ok": False, "code": "FIELD_NOT_ALLOWED", "error": f"Поле '{field}' не разрешено для подтверждения."}
    normalized_value, error = _validate_field_value(field, value)
    if error:
        return {"ok": False, "code": "INVALID_VALUE", "error": error}
    return _apply_field_decision(document_id, field, DECISION_CONFIRM, normalized_value, actor, expected_version)


def reject_field(document_id: str, field: str, actor: str, expected_version: int) -> dict:
    if field not in ALLOWED_STRUCTURED_FIELDS:
        return {"ok": False, "code": "FIELD_NOT_ALLOWED", "error": f"Поле '{field}' не разрешено для подтверждения."}
    return _apply_field_decision(document_id, field, DECISION_REJECT, "", actor, expected_version)


def clear_field(document_id: str, field: str, actor: str, expected_version: int) -> dict:
    if field not in ALLOWED_STRUCTURED_FIELDS:
        return {"ok": False, "code": "FIELD_NOT_ALLOWED", "error": f"Поле '{field}' не разрешено для подтверждения."}
    return _apply_field_decision(document_id, field, DECISION_CLEAR, "", actor, expected_version)
