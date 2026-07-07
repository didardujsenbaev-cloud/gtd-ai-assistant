"""
Natural Planning — сохранение проектов в Google Sheets.
"""

from datetime import date
from sheets import get_sheet


def format_planning_notes(why: str = "", brainstorm: str = "", subtasks: str = "") -> str:
    """Собрать заметки Natural Planning для листа PROJECTS."""
    parts = []
    if why:
        parts.append(f"ПОЧЕМУ: {why}")
    if brainstorm:
        parts.append(f"ИДЕИ: {brainstorm}")
    if subtasks:
        parts.append(f"ПОДЗАДАЧИ: {subtasks}")
    return "\n".join(parts)


def build_project_row(
    name: str,
    outcome: str,
    area: str,
    priority: str,
    next_action: str,
    *,
    why: str = "",
    brainstorm: str = "",
    subtasks: str = "",
    horizon: str = "H1",
    notes_extra: str = "",
) -> list:
    """Собрать строку для листа PROJECTS (16 колонок)."""
    today = date.today().isoformat()
    notes = format_planning_notes(why, brainstorm, subtasks)
    if notes_extra:
        notes = f"{notes_extra}\n{notes}" if notes else notes_extra
    return [
        "", name[:100], outcome[:300], area,
        "", "", "Активен", priority,
        "", next_action[:200], horizon, "", "", notes[:500], today, today,
    ]


def build_action_row(
    action: str,
    project_name: str,
    area: str,
    context_tag: str,
    priority: str,
    *,
    energy: str = "",
    time_min: str = "",
    deadline: str = "",
    notes: str = "",
) -> list:
    """Собрать строку для листа NEXT ACTIONS (16 колонок)."""
    today = date.today().isoformat()
    return [
        "", action[:200], project_name[:100], area,
        context_tag, "Next", priority,
        energy, time_min, deadline, "", "", "",
        notes[:300], today, "",
    ]


def save_project(
    name: str,
    outcome: str,
    area: str,
    priority: str,
    next_action: str,
    context_tag: str,
    *,
    why: str = "",
    brainstorm: str = "",
    subtasks: str = "",
    energy: str = "",
    time_min: str = "",
    deadline: str = "",
    notes_extra: str = "",
    action_notes: str = "",
) -> None:
    """Сохранить проект и первое Next Action в Google Sheets."""
    projects_sheet = get_sheet("projects")
    actions_sheet = get_sheet("next_actions")

    project_row = build_project_row(
        name, outcome, area, priority, next_action,
        why=why, brainstorm=brainstorm, subtasks=subtasks,
        notes_extra=notes_extra,
    )
    projects_sheet.append_row(project_row, value_input_option="USER_ENTERED")

    if not action_notes:
        action_notes = f"Проект: {name[:80]}"
    action_row = build_action_row(
        next_action, name, area, context_tag, priority,
        energy=energy, time_min=time_min, deadline=deadline,
        notes=action_notes,
    )
    actions_sheet.append_row(action_row, value_input_option="USER_ENTERED")
