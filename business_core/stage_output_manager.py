"""
Stage Output Manager — Required Output Domain persistence (Phase A: Stage
Output Foundation).

Sole transactional owner of STAGE_OUTPUT_TEMPLATES and
STAGE_OUTPUT_INSTANCES. Mirrors payment_manager.py's role for
COMMERCIAL_MILESTONE_TEMPLATES/PAYMENT_OBLIGATIONS/PAYMENT_TRANSACTIONS
and checklist_manager.py's role for CHECKLIST_INSTANCES/
CHECKLIST_INSTANCE_ITEMS — targeted sheet reads via
sheets.find_row_by_id()/generate_next_id(), never a positional-index
assumption.

Required Output is the actual deliverable/result of a Stage — distinct
from Document Completion Gate (business_core.document_requirements),
Checklist Completion Gate (business_core.checklist_manager), SOP
(business_core.knowledge_manager, purely instructional), and Milestone
(business_core.payment_manager, about money). This module does not
replace or read from any of those; Output Templates only ever
*reference* a Document Template ID/Checklist ID via
"Related Document Template ID"/"Related Checklist ID" for a human's own
verification convenience — this module never validates or checks either
reference against the other registries.

Phase A is deliberately NOT wired into any Stage Completion Gate — see
business_builder.transition_stage_status(). Required/Blocking are stored
on every Output Instance so a future Completion Gate can read them, but
nothing in this module or in transition_stage_status() evaluates them.

This module is deliberately low-level only: no cross-entity relation
validation (that lives in business_core.stage_entity_relations, the
required_output ENTITY_TYPE_DISPATCH entry), no Telegram UX, no Russian
user-facing text. All cross-domain policy (e.g. resolving Default
Required/Blocking at /linkoutput time, sync orchestration) lives in
business_core.business_builder / business_core.telegram_handlers — this
module is the primitive those callers call after their own validation
passes.

Dependencies: only business_core.sheets. Never business_builder or
telegram_handlers. GTD Core is never imported.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


OUTPUT_TYPES = (
    "document", "approval", "decision", "communication", "system_record",
    "payment", "physical_result", "external_status", "other",
)

OUTPUT_STATUSES = (
    "pending", "produced", "submitted", "accepted", "rejected", "waived", "not_applicable",
)

# Phase A §2 (Enum и lifecycle) — the approved allowed-transition map.
# accepted/waived/not_applicable are terminal (empty target sets).
_ALLOWED_OUTPUT_TRANSITIONS: dict[str, frozenset] = {
    "pending":        frozenset({"produced", "submitted", "waived", "not_applicable"}),
    "produced":       frozenset({"submitted", "accepted", "waived"}),
    "submitted":      frozenset({"accepted", "rejected", "waived"}),
    "rejected":       frozenset({"produced", "submitted", "waived"}),
    "accepted":       frozenset(),
    "waived":         frozenset(),
    "not_applicable": frozenset(),
}
TERMINAL_OUTPUT_STATUSES = frozenset({"accepted", "waived", "not_applicable"})

_OUTPUT_TEMPLATE_FIELDS = [
    "Output Template ID", "Biz ID", "Service ID", "Template ID", "Template Stage ID",
    "Title", "Description", "Output Type", "Verification Method",
    "Related Document Template ID", "Related Checklist ID",
    "Default Required", "Default Blocking", "Status", "Notes",
    "Created At", "Last Updated",
]

_OUTPUT_INSTANCE_FIELDS = [
    "Output Instance ID", "Output Template ID", "Business ID", "Service ID", "Object ID",
    "Roadmap ID", "Stage ID",
    "Title Snapshot", "Description Snapshot", "Output Type Snapshot", "Verification Method Snapshot",
    "Related Document Template ID", "Related Checklist ID",
    "Required", "Blocking", "Status",
    "Evidence Type", "Evidence Value",
    "Submitted By", "Submitted At",
    "Accepted By", "Accepted At",
    "Rejected By", "Rejected At", "Rejection Reason",
    "Waived By", "Waived At", "Waiver Reason",
    "Created At", "Last Updated", "Notes",
]


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def validate_output_status_transition(current: str, target: str) -> list[str]:
    """
    Structural lifecycle validation only. Returns a list of human-
    readable error strings; empty list means the transition is allowed.
    Never touches a sheet. Used by update_output_instance_status() (and
    therefore transitively by submit/accept/reject/waive_output_instance())
    as the single point of transition enforcement — Phase A §2 explicitly
    forbids arbitrary transitions without going through this check.
    """
    errors: list[str] = []
    if current not in OUTPUT_STATUSES:
        errors.append(f"Unknown current status {current!r}. Valid: {', '.join(OUTPUT_STATUSES)}.")
    if target not in OUTPUT_STATUSES:
        errors.append(f"Unknown target status {target!r}. Valid: {', '.join(OUTPUT_STATUSES)}.")
    if errors:
        return errors
    if target not in _ALLOWED_OUTPUT_TRANSITIONS.get(current, frozenset()):
        errors.append(f"Transition {current!r} -> {target!r} is not allowed.")
    return errors


# ═══════════════════════════════════════════════════════════════
# ID generation
# ═══════════════════════════════════════════════════════════════

def generate_output_template_id() -> str:
    """SOUT-001, SOUT-002, ..."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("stage_output_templates")
    except Exception as exc:
        log.warning(f"generate_output_template_id error: {exc}")
        return "SOUT-001"


def generate_output_instance_id() -> str:
    """SOUTI-001, SOUTI-002, ..."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("stage_output_instances")
    except Exception as exc:
        log.warning(f"generate_output_instance_id error: {exc}")
        return "SOUTI-001"


# ═══════════════════════════════════════════════════════════════
# Output Template — create / read
# ═══════════════════════════════════════════════════════════════

def create_output_template(
    *,
    biz_id: str,
    title: str,
    output_type: str,
    service_id: str = "",
    template_id: str = "",
    template_stage_id: str = "",
    description: str = "",
    verification_method: str = "",
    related_document_template_id: str = "",
    related_checklist_id: str = "",
    default_required: str = "true",
    default_blocking: str = "true",
    status: str = "active",
    notes: str = "",
) -> dict:
    """
    Create an Output Template in STAGE_OUTPUT_TEMPLATES.

    biz_id/title/output_type are required (Phase A §Часть 6, item 24).
    output_type must be one of OUTPUT_TYPES.

    Returns:
        {"ok": bool, "output_template_id": str, "code": str, "error": str | None}
    """
    if not biz_id:
        return {"ok": False, "output_template_id": "", "code": "", "error": "biz_id обязателен"}
    if not title:
        return {"ok": False, "output_template_id": "", "code": "", "error": "title обязателен"}
    if output_type not in OUTPUT_TYPES:
        return {
            "ok": False, "output_template_id": "", "code": "INVALID_OUTPUT_TYPE",
            "error": f"Недопустимый output_type {output_type!r}. Допустимые значения: {', '.join(OUTPUT_TYPES)}",
        }

    try:
        from business_core.sheets import append_business_row, row_from_header_map

        output_template_id = generate_output_template_id()
        now = datetime.now().strftime("%Y-%m-%d")
        values = {
            "Output Template ID": output_template_id, "Biz ID": biz_id,
            "Service ID": service_id, "Template ID": template_id, "Template Stage ID": template_stage_id,
            "Title": title, "Description": description, "Output Type": output_type,
            "Verification Method": verification_method,
            "Related Document Template ID": related_document_template_id,
            "Related Checklist ID": related_checklist_id,
            "Default Required": default_required, "Default Blocking": default_blocking,
            "Status": status, "Notes": notes,
            "Created At": now, "Last Updated": now,
        }
        row = row_from_header_map(_OUTPUT_TEMPLATE_FIELDS, values)
        append_business_row("stage_output_templates", row)
        log.info(f"create_output_template: {output_template_id} / {title}")
        return {"ok": True, "output_template_id": output_template_id, "code": "OUTPUT_TEMPLATE_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_output_template error: {exc}")
        return {"ok": False, "output_template_id": "", "code": "", "error": str(exc)}


def find_output_template_by_id(output_template_id: str) -> Optional[dict]:
    """Header-mapped single-row read of STAGE_OUTPUT_TEMPLATES by Output
    Template ID, or None if not found."""
    if not output_template_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        found = find_row_by_id("stage_output_templates", output_template_id)
        return found[1] if found else None
    except Exception as exc:
        log.error(f"find_output_template_by_id({output_template_id}) error: {exc}")
        return None


def list_output_templates_for_template_stage(template_stage_id: str) -> list[dict]:
    """All STAGE_OUTPUT_TEMPLATES rows whose Template Stage ID matches,
    in sheet order."""
    if not template_stage_id:
        return []
    try:
        from business_core.sheets import read_business_sheet
        rows = read_business_sheet("stage_output_templates")
        return [r for r in rows if r.get("Template Stage ID", "") == template_stage_id]
    except Exception as exc:
        log.error(f"list_output_templates_for_template_stage({template_stage_id}) error: {exc}")
        return []


# ═══════════════════════════════════════════════════════════════
# Output Instance — create / read
# ═══════════════════════════════════════════════════════════════

def _find_existing_instance(output_template_id: str, stage_id: str) -> Optional[dict]:
    """Read-only idempotency lookup: an existing STAGE_OUTPUT_INSTANCES
    row for the same (Output Template ID, Stage ID) pair, or None."""
    for row in list_output_instances_for_stage(stage_id):
        if row.get("Output Template ID", "") == output_template_id:
            return row
    return None


def create_output_instance(
    output_template_id: str,
    stage_id: str,
    *,
    roadmap_id: str = "",
    business_id: str = "",
    service_id: str = "",
    object_id: str = "",
    required: Optional[str] = None,
    blocking: Optional[str] = None,
) -> dict:
    """
    Create an Output Instance in STAGE_OUTPUT_INSTANCES, snapshotting
    Title/Description/Output Type/Verification Method from the Output
    Template at creation time.

    Idempotent per (Output Template ID, Stage ID) — a second call with
    the same pair returns the existing instance (ok=True,
    code="OUTPUT_INSTANCE_ALREADY_EXISTS") instead of creating a
    duplicate row.

    Defensive fallback (Phase A §Часть 3, item 13 / confirmed decision
    §4): if `required`/`blocking` are explicitly passed (not None), they
    are used as-is; if either is None, the Output Template's own Default
    Required/Default Blocking is used instead. This exists for direct
    manager calls (bypassing the relation layer, where /linkoutput
    already resolves the fallback itself) and future automation — it
    does NOT imply STAGE_ENTITY_RELATIONS ever stores a blank Required/
    Blocking value.

    Returns:
        {"ok": bool, "output_instance_id": str, "code": str, "error": str | None}
    """
    if not output_template_id:
        return {"ok": False, "output_instance_id": "", "code": "", "error": "output_template_id обязателен"}
    if not stage_id:
        return {"ok": False, "output_instance_id": "", "code": "", "error": "stage_id обязателен"}

    template = find_output_template_by_id(output_template_id)
    if template is None:
        return {
            "ok": False, "output_instance_id": "", "code": "OUTPUT_TEMPLATE_NOT_FOUND",
            "error": f"Output Template {output_template_id!r} не найден",
        }

    existing = _find_existing_instance(output_template_id, stage_id)
    if existing is not None:
        return {
            "ok": True, "output_instance_id": existing.get("Output Instance ID", ""),
            "code": "OUTPUT_INSTANCE_ALREADY_EXISTS", "error": None,
        }

    resolved_required = required if required is not None else template.get("Default Required", "true")
    resolved_blocking = blocking if blocking is not None else template.get("Default Blocking", "true")

    try:
        from business_core.sheets import append_business_row, row_from_header_map

        output_instance_id = generate_output_instance_id()
        now = _now_utc_str()
        values = {
            "Output Instance ID": output_instance_id, "Output Template ID": output_template_id,
            "Business ID": business_id, "Service ID": service_id, "Object ID": object_id,
            "Roadmap ID": roadmap_id, "Stage ID": stage_id,
            "Title Snapshot": template.get("Title", ""),
            "Description Snapshot": template.get("Description", ""),
            "Output Type Snapshot": template.get("Output Type", ""),
            "Verification Method Snapshot": template.get("Verification Method", ""),
            "Related Document Template ID": template.get("Related Document Template ID", ""),
            "Related Checklist ID": template.get("Related Checklist ID", ""),
            "Required": resolved_required, "Blocking": resolved_blocking, "Status": "pending",
            "Evidence Type": "", "Evidence Value": "",
            "Submitted By": "", "Submitted At": "",
            "Accepted By": "", "Accepted At": "",
            "Rejected By": "", "Rejected At": "", "Rejection Reason": "",
            "Waived By": "", "Waived At": "", "Waiver Reason": "",
            "Created At": now, "Last Updated": now, "Notes": "",
        }
        row = row_from_header_map(_OUTPUT_INSTANCE_FIELDS, values)
        append_business_row("stage_output_instances", row)
        log.info(f"create_output_instance: {output_instance_id} / template={output_template_id} / stage={stage_id}")
        return {"ok": True, "output_instance_id": output_instance_id, "code": "OUTPUT_INSTANCE_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_output_instance error: {exc}")
        return {"ok": False, "output_instance_id": "", "code": "", "error": str(exc)}


def find_output_instance_by_id(output_instance_id: str) -> Optional[dict]:
    """Header-mapped single-row read of STAGE_OUTPUT_INSTANCES by Output
    Instance ID, or None if not found."""
    if not output_instance_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        found = find_row_by_id("stage_output_instances", output_instance_id)
        return found[1] if found else None
    except Exception as exc:
        log.error(f"find_output_instance_by_id({output_instance_id}) error: {exc}")
        return None


def list_output_instances_for_stage(stage_id: str) -> list[dict]:
    """All STAGE_OUTPUT_INSTANCES rows whose Stage ID matches, in sheet
    order."""
    if not stage_id:
        return []
    try:
        from business_core.sheets import read_business_sheet
        rows = read_business_sheet("stage_output_instances")
        return [r for r in rows if r.get("Stage ID", "") == stage_id]
    except Exception as exc:
        log.error(f"list_output_instances_for_stage({stage_id}) error: {exc}")
        return []


# ═══════════════════════════════════════════════════════════════
# Output Instance — lifecycle
# ═══════════════════════════════════════════════════════════════

def update_output_instance_status(output_instance_id: str, target_status: str, **audit_fields) -> dict:
    """
    Low-level Status write — validates the transition via
    validate_output_status_transition() before writing anything.
    `audit_fields` are extra column -> value writes applied together with
    the Status change in the same call (e.g. Accepted By/Accepted At) —
    keys must be real STAGE_OUTPUT_INSTANCES column names.

    This is the single write path used internally by
    submit_output_evidence()/accept_output_instance()/
    reject_output_instance()/waive_output_instance() and by
    /updateoutput (restricted at the Telegram layer to target_status in
    {"produced", "not_applicable"} only — this function itself does not
    know about that restriction and enforces only the transition matrix).

    Returns:
        {"ok": bool, "code": str, "error": str | None}
    """
    if not output_instance_id:
        return {"ok": False, "code": "OUTPUT_INSTANCE_NOT_FOUND", "error": "output_instance_id обязателен"}

    try:
        from business_core.sheets import find_row_by_id, get_business_sheet, get_header_index_map

        found = find_row_by_id("stage_output_instances", output_instance_id)
        if found is None:
            return {"ok": False, "code": "OUTPUT_INSTANCE_NOT_FOUND", "error": f"Output Instance {output_instance_id!r} не найден"}
        row_num, current = found

        current_status = current.get("Status", "")
        errors = validate_output_status_transition(current_status, target_status)
        if errors:
            return {"ok": False, "code": "INVALID_STATUS_TRANSITION", "error": "; ".join(errors)}

        sheet = get_business_sheet("stage_output_instances")
        idx = get_header_index_map(sheet.row_values(1))

        sheet.update_cell(row_num, idx["Status"] + 1, target_status)
        for field, value in audit_fields.items():
            if field in idx:
                sheet.update_cell(row_num, idx[field] + 1, value)
        if "Last Updated" in idx:
            sheet.update_cell(row_num, idx["Last Updated"] + 1, _now_utc_str())

        return {"ok": True, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_output_instance_status({output_instance_id}) error: {exc}")
        return {"ok": False, "code": "", "error": str(exc)}


def submit_output_evidence(output_instance_id: str, evidence_type: str, evidence_value: str, submitted_by: str) -> dict:
    """
    Save Evidence Type/Value and transition to "submitted" (allowed from
    pending/produced/rejected per the transition matrix). Both
    evidence_type and evidence_value must be non-blank — Phase A does
    not verify the value against Drive/Document Registry, it only stores
    what was provided.
    """
    if not (evidence_type or "").strip():
        return {"ok": False, "code": "EVIDENCE_TYPE_REQUIRED", "error": "evidence_type обязателен"}
    if not (evidence_value or "").strip():
        return {"ok": False, "code": "EVIDENCE_VALUE_REQUIRED", "error": "evidence_value обязателен"}

    now = _now_utc_str()
    result = update_output_instance_status(
        output_instance_id, "submitted",
        **{
            "Evidence Type": evidence_type, "Evidence Value": evidence_value,
            "Submitted By": submitted_by, "Submitted At": now,
        },
    )
    if not result["ok"]:
        return result
    return {"ok": True, "code": "OUTPUT_SUBMITTED", "error": None}


def accept_output_instance(output_instance_id: str, accepted_by: str) -> dict:
    """Transition to "accepted" (allowed only from produced/submitted per
    the transition matrix)."""
    now = _now_utc_str()
    result = update_output_instance_status(
        output_instance_id, "accepted",
        **{"Accepted By": accepted_by, "Accepted At": now},
    )
    if not result["ok"]:
        return result
    return {"ok": True, "code": "OUTPUT_ACCEPTED", "error": None}


def reject_output_instance(output_instance_id: str, rejected_by: str, reason: str) -> dict:
    """Transition to "rejected" (allowed only from submitted per the
    transition matrix). reason is required."""
    if not (reason or "").strip():
        return {"ok": False, "code": "REJECTION_REASON_REQUIRED", "error": "reason обязателен"}

    now = _now_utc_str()
    result = update_output_instance_status(
        output_instance_id, "rejected",
        **{"Rejected By": rejected_by, "Rejected At": now, "Rejection Reason": reason},
    )
    if not result["ok"]:
        return result
    return {"ok": True, "code": "OUTPUT_REJECTED", "error": None}


def waive_output_instance(output_instance_id: str, waived_by: str, reason: str) -> dict:
    """Transition to "waived" (allowed from pending/produced/submitted/
    rejected per the transition matrix). reason is required."""
    if not (reason or "").strip():
        return {"ok": False, "code": "WAIVER_REASON_REQUIRED", "error": "reason обязателен"}

    now = _now_utc_str()
    result = update_output_instance_status(
        output_instance_id, "waived",
        **{"Waived By": waived_by, "Waived At": now, "Waiver Reason": reason},
    )
    if not result["ok"]:
        return result
    return {"ok": True, "code": "OUTPUT_WAIVED", "error": None}
