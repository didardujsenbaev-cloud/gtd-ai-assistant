"""
Phase 34C: Stage Domain transition-orchestration architecture guards
(ADR-017). Complements test_roadmap_architecture_guards.py's existing
Stage-persistence-ownership checks (unchanged by this phase) with the
new transition-boundary invariants:

  ROADMAP_STAGES writers                        == {roadmap_manager.py}
  Stage transition/eligibility policy owner      == business_builder.py only
  telegram_handlers.py duplicates transition policy  == NO
  roadmap_manager imports business_builder/telegram_handlers == NO

No network, no Google Sheets access — pure AST/source inspection of
files already on disk.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
BUSINESS_CORE = WORKSPACE / "business_core"


def _imported_module_names(path: Path) -> set[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
                names.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
            names.add(node.module.split(".")[-1])
    return names


def _files_writing_registry(candidate_files: list[Path], sheet_keys: set[str]) -> set[str]:
    """Scans each file's AST for a call to append_business_row/
    batch_append_business_rows/update_cell whose first literal string
    argument matches one of sheet_keys (append_*) — a simple, targeted
    write-ownership scan, same pattern used by the Roadmap Domain's own
    architecture guards."""
    hits: set[str] = set()
    for path in candidate_files:
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if fname in ("append_business_row", "batch_append_business_rows"):
                if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in sheet_keys:
                    hits.add(path.name)
    return hits


class TestRoadmapStagesWriteOwnershipUnchanged(unittest.TestCase):
    """ADR-017 Decision 1: roadmap_manager.py remains the sole
    transactional owner of ROADMAP_STAGES writes — unchanged by
    Phase 34C's new transition-orchestration layer."""

    def test_only_roadmap_manager_writes_roadmap_stages(self):
        candidates = [p for p in BUSINESS_CORE.glob("*.py") if p.name != "roadmap_manager.py"]
        found = _files_writing_registry(candidates, {"roadmap_stages"})
        self.assertEqual(found, set(), f"Only roadmap_manager.py may write roadmap_stages, found: {found}")


class TestStageTransitionOwnerIsBusinessBuilder(unittest.TestCase):
    """ADR-017 Decision 2/6: transition_stage_status() (the Roadmap-
    eligibility + transition-matrix check) exists exactly once, in
    business_builder.py — never duplicated in roadmap_manager.py or
    telegram_handlers.py."""

    def test_transition_stage_status_defined_in_business_builder(self):
        import business_core.business_builder as bb
        self.assertTrue(callable(getattr(bb, "transition_stage_status", None)))
        self.assertTrue(callable(getattr(bb, "update_stage_admin_fields", None)))

    def test_transition_matrix_constant_lives_only_in_business_builder(self):
        for path in BUSINESS_CORE.glob("*.py"):
            if path.name == "business_builder.py":
                continue
            src = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "_STAGE_ORDINARY_TRANSITIONS", src,
                f"{path.name} must not define its own copy of the Stage transition matrix",
            )

    def test_roadmap_manager_does_not_implement_eligibility_or_transition_policy(self):
        """roadmap_manager.py's low-level functions must not reference
        Roadmap-status eligibility codes — that policy belongs solely
        to business_builder.transition_stage_status()."""
        path = BUSINESS_CORE / "roadmap_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("ROADMAP_ON_HOLD", "ROADMAP_COMPLETED", "ROADMAP_CANCELLED",
                          "STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION"):
            self.assertNotIn(
                forbidden, src,
                f"roadmap_manager.py must not reference {forbidden} — eligibility/"
                f"transition policy belongs solely to business_builder.py (ADR-017 §2).",
            )


class TestTelegramHandlersDoesNotDuplicateStageTransitionPolicy(unittest.TestCase):
    """ADR-017 Decision 2/14/20: telegram_handlers.py must only parse
    input, call the canonical orchestration API, and render its
    structured result — never re-implement Roadmap eligibility or the
    Stage transition matrix itself."""

    def _updatestage_body(self) -> str:
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("async def updatestage_cmd")
        end = src.index("\nasync def ", start + 10)
        return src[start:end]

    def test_updatestage_calls_only_transition_stage_status(self):
        body = self._updatestage_body()
        self.assertIn("transition_stage_status", body)
        for forbidden_call in (
            "update_stage_status_in_sheet(",
            "recalculate_roadmap_progress(",
            "maybe_complete_roadmap(",
            "find_roadmap_by_id(",
        ):
            self.assertNotIn(
                forbidden_call, body,
                f"updatestage_cmd must not call {forbidden_call.rstrip('(')} directly — "
                f"that orchestration lives solely inside business_builder."
                f"transition_stage_status() (ADR-017 §2/§6).",
            )

    def test_updatestage_body_never_branches_on_roadmap_eligibility_status(self):
        """Scoped strictly to updatestage_cmd's own body (not the whole
        file, which legitimately displays Roadmap/Business status
        elsewhere for unrelated commands) — confirms it never branches
        on a Roadmap status string itself; it only reads fields
        business_builder.transition_stage_status() already computed."""
        body = self._updatestage_body()
        for snippet in ('== "on_hold"', 'roadmap_status_before == "completed"',
                        'roadmap_status_before == "cancelled"'):
            self.assertNotIn(
                snippet, body,
                f"updatestage_cmd must not branch on Roadmap eligibility status ({snippet}) — "
                f"that decision belongs solely to business_builder.py.",
            )


class TestStageManagerDependencyDirection(unittest.TestCase):
    """ADR-017 Decision 21: roadmap_manager.py must not import
    business_builder, telegram_handlers, person_manager, or
    organization_manager — the one documented pre-existing exception
    (service_manager inside _resolve_template_id) is unchanged and not
    expanded by this phase."""

    _FORBIDDEN = {"business_builder", "telegram_handlers", "person_manager", "organization_manager"}

    def test_no_forbidden_imports(self):
        path = BUSINESS_CORE / "roadmap_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"roadmap_manager.py must not import: {found}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
