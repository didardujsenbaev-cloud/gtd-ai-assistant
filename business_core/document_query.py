"""
Phase 16C (architecture refinement): reusable, read-only Business Core
query layer over DOCUMENT_CONTENT (+ the minimal DOCUMENT_REGISTRY
fields needed to describe a result — Document Name, File Name, Mime
Type).

This module exists so Telegram handlers never read Google Sheets
directly and never know column names ("Content Status", "AI Summary",
"Extracted Fields JSON", ...) — they call get_document_analysis() (or
the narrower get_document_status()/get_document_summary() accessors),
get back an immutable DocumentAnalysisResult, and only render it.

Strictly read-only: every function here does at most two single-row
Sheets reads (document_registry, document_content) and never calls
Anthropic, never touches Google Drive, and never writes anything.
No schema change — DOCUMENT_REGISTRY/DOCUMENT_CONTENT headers are
untouched; this module only interprets what's already there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DocumentAnalysisResult:
    """
    Immutable result of a document-analysis lookup.

    status is one of:
        "not_found"   — document_id doesn't exist in DOCUMENT_REGISTRY
        "no_content"  — registered, but no DOCUMENT_CONTENT row yet
        "pending" | "processing" | "failed" | "unsupported" | "completed"
                      — DOCUMENT_CONTENT's own Content Status, verbatim
    """
    status: str
    document_id: str = ""
    document_name: str = ""
    file_name: str = ""
    mime_type: str = ""
    detected_document_type: str = ""
    summary: str = ""
    fields: dict = field(default_factory=dict)
    fields_valid: bool = True
    keywords: tuple = ()
    language: str = ""
    page_count: str = ""
    suggested_template_id: str = ""
    template_match_confidence: str = ""
    completed_at: str = ""
    updated_at: str = ""
    error: str = ""


def _parse_fields_json(raw: str) -> tuple[dict, bool]:
    """Returns (fields_dict, valid). An empty/absent value is valid and
    empty. Anything that isn't parseable JSON, or parses to something
    other than a JSON object, is reported as invalid (fields_dict {})."""
    if not raw or not raw.strip():
        return {}, True
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}, False
    if not isinstance(data, dict):
        return {}, False
    return data, True


def _parse_keywords_json(raw: str) -> tuple:
    """Returns a tuple of keyword strings, or an empty tuple for
    absent/invalid/non-list input — never raises."""
    if not raw or not raw.strip():
        return ()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ()
    if not isinstance(data, list):
        return ()
    return tuple(str(k) for k in data)


def get_document_analysis(document_id: str) -> DocumentAnalysisResult:
    """
    The single entry point callers (Telegram handlers or anything else)
    should use. Always returns a DocumentAnalysisResult — never None,
    never raises for the expected "not found"/"no content yet" cases,
    those are just status values on the result.

    Read-only: at most one document_registry row read and one
    document_content row read (via
    business_core.document_intelligence.get_content_status(), itself a
    single find_row_by_id() call) — zero writes, zero AI calls, zero
    Drive calls.
    """
    from business_core.sheets import find_row_by_id
    from business_core.document_intelligence import get_content_status

    doc_found = find_row_by_id("document_registry", document_id)
    if not doc_found:
        return DocumentAnalysisResult(status="not_found", document_id=document_id)
    _, doc_row = doc_found

    document_name = doc_row.get("Document Name", "")
    file_name = doc_row.get("File Name", "")
    mime_type = doc_row.get("Mime Type", "")

    content = get_content_status(document_id)
    if content is None:
        return DocumentAnalysisResult(
            status="no_content",
            document_id=document_id,
            document_name=document_name,
            file_name=file_name,
            mime_type=mime_type,
        )

    status = (content.get("Content Status") or "").strip() or "pending"
    fields_dict, fields_valid = _parse_fields_json(content.get("Extracted Fields JSON", ""))
    keywords = _parse_keywords_json(content.get("Keywords JSON", ""))

    return DocumentAnalysisResult(
        status=status,
        document_id=document_id,
        document_name=document_name,
        file_name=file_name,
        mime_type=mime_type,
        detected_document_type=content.get("Detected Document Type", ""),
        summary=content.get("AI Summary", ""),
        fields=fields_dict,
        fields_valid=fields_valid,
        keywords=keywords,
        language=content.get("Language", ""),
        page_count=content.get("Page Count", ""),
        suggested_template_id=content.get("Suggested Document Template ID", ""),
        template_match_confidence=content.get("Template Match Confidence", ""),
        completed_at=content.get("Analysis Completed At", ""),
        updated_at=content.get("Updated At", ""),
        error=content.get("Analysis Error", ""),
    )


def get_document_status(document_id: str) -> str:
    """Narrow accessor: just the status string, for callers that don't
    need the full result."""
    return get_document_analysis(document_id).status


def get_document_summary(document_id: str) -> str:
    """Narrow accessor: just the AI summary (empty string if none)."""
    return get_document_analysis(document_id).summary
