"""
Phase 36C: Task Domain architecture guards (ADR-019). Mirrors the
pattern established in test_organization_architecture_guards.py — pure
AST/source inspection, no network, no Google Sheets.

  TASK registries writers (TASK_REGISTRY/TASK_ASSIGNMENTS) == {task_manager.py}
  Task orchestration policy owner                          == business_builder.py only
  task_manager imports business_builder/telegram_handlers   == NO
  Closed domains import task_manager                        == NO
  Telegram contains Task eligibility policy                 == NO (none exists yet)
  GTD files import Task Domain                               == NO
  /tasks implementation unchanged and GTD-owned              == YES
  No Task->Stage/Roadmap write path exists                   == YES
  Assignment cache not admin-editable                        == YES
  No title-based dedup                                       == YES
  No arbitrary first selection                                == YES
  Sensitive values not logged                                 == YES
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
BUSINESS_CORE = WORKSPACE / "business_core"

GTD_FORBIDDEN = {"inbox_processor", "telegram_bot", "project_planner", "calendar_sync"}


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


class TestTaskRegistryWriteOwnership(unittest.TestCase):

    def test_only_task_manager_writes_task_registries(self):
        candidates = [p for p in BUSINESS_CORE.glob("*.py") if p.name != "task_manager.py"]
        found = _files_writing_registry(candidates, {"task_registry", "task_assignments"})
        self.assertEqual(found, set(), f"Only task_manager.py may write Task registries, found: {found}")


class TestTaskOrchestrationOwnerIsBusinessBuilder(unittest.TestCase):

    def test_all_orchestration_functions_defined_in_business_builder(self):
        import business_core.business_builder as bb
        for fn in ("create_business_task", "update_task_admin_fields", "transition_task_status",
                   "assign_task", "unassign_task", "task_assignment_cache_is_consistent"):
            self.assertTrue(callable(getattr(bb, fn, None)), f"{fn} must be defined in business_builder.py")

    def test_task_manager_does_not_implement_cross_entity_eligibility_codes(self):
        path = BUSINESS_CORE / "task_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "ROLE_PAUSED", "ROLE_ARCHIVED", "PERSON_ARCHIVED", "PERSON_NOT_LINKED_TO_BUSINESS",
            "ROADMAP_COMPLETED", "ROADMAP_CANCELLED", "ROADMAP_ON_HOLD", "STAGE_TERMINAL",
            "MULTIPLE_TASK_IDEMPOTENCY_MATCHES", "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR",
            "TASK_ENTITY_RELATION_MISMATCH",
        ):
            self.assertNotIn(
                forbidden, src,
                f"task_manager.py must not reference {forbidden} — cross-entity eligibility/"
                f"lifecycle/idempotency policy belongs solely to business_builder.py (ADR-019 §7/§17-20).",
            )


class TestTaskManagerDependencyDirection(unittest.TestCase):

    _FORBIDDEN = {"business_builder", "telegram_handlers"}

    def test_task_manager_no_forbidden_imports(self):
        path = BUSINESS_CORE / "task_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"task_manager.py must not import: {found}")

    def test_task_manager_no_russian_wording(self):
        """Task Manager's log messages are English (ADR-019 §26 — no
        Russian user-facing wording in task_manager.py/business_builder.py).
        Docstrings retain Russian for repository-wide consistency with
        every other manager module; only log/user-facing strings are
        checked here."""
        path = BUSINESS_CORE / "task_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = getattr(node.func, "attr", None)
                if fname in ("info", "warning", "error") and getattr(node.func, "value", None) is not None:
                    value_name = getattr(node.func.value, "id", "")
                    if value_name == "log":
                        for arg in node.args:
                            if isinstance(arg, ast.JoinedStr):
                                for part in arg.values:
                                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                                        self.assertFalse(
                                            any(ch in "бвгдежзийклмнопрстуфхцчшщъыьэюя" for ch in part.value.lower()),
                                            f"task_manager.py log call contains Russian text: {part.value!r}",
                                        )


class TestClosedDomainsDoNotImportTaskManager(unittest.TestCase):

    def test_no_closed_domain_file_imports_task_manager(self):
        closed_domain_files = (
            "organization_manager.py", "work_assignment_manager.py",
            "roadmap_manager.py", "stage_entity_relations.py",
            "object_manager.py", "service_manager.py", "person_manager.py",
        )
        for filename in closed_domain_files:
            path = BUSINESS_CORE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"task_manager"}
            self.assertEqual(found, set(), f"{filename} must not import task_manager")


class TestGtdFilesDoNotImportTaskDomain(unittest.TestCase):

    def test_gtd_files_do_not_import_task_modules(self):
        gtd_files = ("inbox_processor.py", "telegram_bot.py", "project_planner.py", "calendar_sync.py")
        for filename in gtd_files:
            path = WORKSPACE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"task_manager", "business_builder"}
            # business_builder is a Business Core module; GTD files must
            # never import it regardless of Task Domain — but task_manager
            # is the specific new-this-phase check.
            self.assertNotIn("task_manager", found, f"{filename} must not import task_manager")


class TestTasksCommandUnchangedAndGtdOwned(unittest.TestCase):

    def test_tasks_command_still_registered_in_telegram_bot(self):
        path = WORKSPACE / "telegram_bot.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn('CommandHandler("tasks", show_tasks)', src)

    def test_business_core_does_not_register_tasks_command(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        if not path.exists():
            return
        src = path.read_text(encoding="utf-8")
        self.assertNotIn('CommandHandler("tasks"', src)

    def test_business_task_commands_registered_exactly_once(self):
        """Phase 36D: each Business Task command is registered exactly
        once — no duplicate CommandHandler registration."""
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for name in ("newbctask", "bctasks", "bctask", "updatetask", "assigntask", "reassigntask", "unassigntask"):
            self.assertEqual(
                src.count(f'CommandHandler("{name}"'), 1,
                f"/{name} must be registered exactly once",
            )

    def test_business_task_commands_do_not_collide_with_tasks(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn('CommandHandler("tasks"', src)

    def test_business_task_commands_do_not_collide_with_existing_commands(self):
        """No new Business Task command name duplicates a pre-existing,
        unrelated command's exact string registration."""
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        new_names = {"newbctask", "bctasks", "bctask", "updatetask", "assigntask", "reassigntask", "unassigntask"}
        import re
        all_registered = re.findall(r'CommandHandler\("([a-zA-Z_]+)"', src)
        counts = {}
        for name in all_registered:
            counts[name] = counts.get(name, 0) + 1
        for name in new_names:
            self.assertEqual(counts.get(name, 0), 1, f"/{name} must appear exactly once across all registrations")


class TestNoTaskStageOrRoadmapWritePath(unittest.TestCase):

    def test_business_builder_task_functions_never_write_stage_or_roadmap(self):
        path = BUSINESS_CORE / "business_builder.py"
        src = path.read_text(encoding="utf-8")
        for fn_name in (
            "create_business_task", "update_task_admin_fields", "transition_task_status",
            "assign_task", "unassign_task",
        ):
            start = src.index(f"def {fn_name}(")
            end = src.index("\ndef ", start + 10)
            body = src[start:end]
            for forbidden in (
                "update_stage_status_in_sheet(", "update_stage_fields(",
                "recalculate_roadmap_progress(", "maybe_complete_roadmap(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not write Stage/Roadmap state directly")


class TestAssignmentCacheNotAdminEditable(unittest.TestCase):

    def test_admin_editable_fields_exclude_cache_and_status(self):
        import business_core.task_manager as tm
        for forbidden in ("Responsible Role ID", "Assignee Person ID", "Status"):
            self.assertNotIn(forbidden, tm._TASK_ADMIN_EDITABLE_FIELDS)

    def test_admin_editable_fields_exclude_identity_and_relations(self):
        import business_core.task_manager as tm
        for forbidden in ("Task ID", "Business ID", "Created At", "Client ID", "Object ID", "Service ID", "Roadmap ID", "Stage ID"):
            self.assertNotIn(forbidden, tm._TASK_ADMIN_EDITABLE_FIELDS)


class TestNoTitleBasedDedup(unittest.TestCase):

    def test_create_business_task_never_looks_up_by_title(self):
        path = BUSINESS_CORE / "business_builder.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("def create_business_task(")
        end = src.index("\ndef ", start + 10)
        body = src[start:end]
        self.assertNotIn("find_tasks_by_title", body)
        self.assertNotIn('"Title"] ==', body)


class TestNoArbitraryFirstSelection(unittest.TestCase):

    def test_multiple_matches_never_pick_index_zero_silently(self):
        path = BUSINESS_CORE / "business_builder.py"
        src = path.read_text(encoding="utf-8")
        # Every "matches[0]"/"active_assignments[0]" access in the Task
        # functions must be reached only AFTER a len(...) > 1 integrity
        # check has already returned — spot-check the two known
        # multiple-match sites both branch on len() before indexing.
        for fn_name in ("create_business_task", "assign_task", "unassign_task"):
            start = src.index(f"def {fn_name}(")
            end = src.index("\ndef ", start + 10)
            body = src[start:end]
            if "len(matches) > 1" in body:
                self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))
            if "len(active_assignments) > 1" in body:
                self.assertLess(body.index("len(active_assignments) > 1"), body.index("active_assignments[0]"))


class TestSensitiveTaskValuesAreNotLogged(unittest.TestCase):

    _DISALLOWED_LOG_TOKENS = ("Description", "Notes", "phone", "update.message.text")

    def test_task_manager_does_not_log_disallowed_fields(self):
        path = BUSINESS_CORE / "task_manager.py"
        src = path.read_text(encoding="utf-8")
        log_lines = [line for line in src.splitlines() if "log.error(" in line or "log.warning(" in line or "log.info(" in line]
        for line in log_lines:
            for token in self._DISALLOWED_LOG_TOKENS:
                self.assertNotIn(token, line, f"task_manager.py logs disallowed token {token!r}: {line}")

    def test_business_builder_task_functions_do_not_log_disallowed_fields(self):
        path = BUSINESS_CORE / "business_builder.py"
        src = path.read_text(encoding="utf-8")
        for fn_name in (
            "create_business_task", "update_task_admin_fields", "transition_task_status",
            "assign_task", "unassign_task",
        ):
            start = src.index(f"def {fn_name}(")
            end = src.index("\ndef ", start + 10)
            body = src[start:end]
            log_lines = [line for line in body.splitlines() if "log.error(" in line or "log.warning(" in line or "log.info(" in line]
            for line in log_lines:
                for token in self._DISALLOWED_LOG_TOKENS:
                    self.assertNotIn(token, line, f"{fn_name} logs disallowed token {token!r}: {line}")


# ─────────────────────────────────────────────────────────────
# Phase 36D (ADR-019 §18): Task caller (Telegram) architecture guards.
# ─────────────────────────────────────────────────────────────

_TASK_COMMANDS = (
    "newbctask_cmd", "bctasks_cmd", "bctask_cmd", "updatetask_cmd",
    "assigntask_cmd", "reassigntask_cmd", "unassigntask_cmd",
)


def _th_function_body(fn_name: str) -> str:
    path = BUSINESS_CORE / "telegram_handlers.py"
    src = path.read_text(encoding="utf-8")
    start = src.index(f"async def {fn_name}")
    rest = src[start + 10:]
    candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
    end = start + 10 + min(candidates) if candidates else len(src)
    return src[start:end]


class TestTaskCommandsCallOnlyCanonicalOrchestration(unittest.TestCase):

    def test_no_low_level_task_manager_write_calls(self):
        forbidden = (
            "task_manager.create_task(", "task_manager.update_task_admin_fields(",
            "task_manager.update_task_status(", "task_manager.update_task_assignment_cache(",
            "task_manager.create_task_assignment(", "task_manager.end_task_assignment(",
        )
        for fn_name in _TASK_COMMANDS:
            body = _th_function_body(fn_name)
            for call in forbidden:
                self.assertNotIn(call, body, f"{fn_name} must not call low-level {call.rstrip('(')} directly")

    def test_only_read_only_task_manager_functions_called(self):
        allowed_reads = ("find_task_by_id", "list_tasks", "get_current_task_assignment", "TASK_STATUS")
        for fn_name in ("bctasks_cmd", "bctask_cmd"):
            body = _th_function_body(fn_name)
            self.assertTrue(
                any(f"task_manager.{name}" in body or f"import {name}" in body for name in allowed_reads),
                f"{fn_name} should use a read-only task_manager API",
            )

    def test_no_policy_duplication_in_telegram(self):
        """Telegram commands must not re-derive eligibility/transition/
        idempotency policy — every branch must come from the
        orchestrator's own result code."""
        for fn_name in _TASK_COMMANDS:
            body = _th_function_body(fn_name)
            for snippet in (
                '== "paused"', '== "archived"', '== "planned"',
                "is_person_archived", "find_department_by_id", "find_role_by_id",
                "_TASK_ORDINARY_TRANSITIONS",
            ):
                self.assertNotIn(snippet, body, f"{fn_name} must not re-derive policy ({snippet})")


class TestCentralizedTaskUXMappingExists(unittest.TestCase):

    def test_mapping_functions_exist(self):
        import business_core.telegram_handlers as th
        for fn in ("_task_creation_message", "_task_admin_message", "_task_transition_message", "_task_assignment_message"):
            self.assertTrue(callable(getattr(th, fn, None)))

    def test_mapping_functions_defined_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn in ("_task_creation_message", "_task_admin_message", "_task_transition_message", "_task_assignment_message"):
            self.assertEqual(src.count(f"def {fn}("), 1)

    def test_assign_and_reassign_use_same_shared_mapping(self):
        assign_body = _th_function_body("assigntask_cmd")
        reassign_body = _th_function_body("reassigntask_cmd")
        self.assertIn("_task_assignment_message(", assign_body)
        self.assertIn("_task_assignment_message(", reassign_body)


class TestUnknownTaskCodeSafeFallback(unittest.TestCase):

    def test_all_mapping_functions_have_fallback(self):
        import business_core.telegram_handlers as th
        self.assertIn("❌", th._task_creation_message({"ok": False, "code": "XXX", "error": "x"}))
        self.assertIn("❌", th._task_admin_message({"ok": False, "code": "XXX", "error": "x"}, "TSK-001"))
        self.assertIn("❌", th._task_transition_message({"ok": False, "code": "XXX", "error": "x"}, "TSK-001"))
        self.assertIn("❌", th._task_assignment_message({"ok": False, "code": "XXX", "error": "x"}, "TSK-001"))


class TestNoAiOrGtdIntegrationIntroduced(unittest.TestCase):

    def test_task_commands_do_not_import_gtd_or_ai_modules(self):
        for fn_name in _TASK_COMMANDS:
            body = _th_function_body(fn_name)
            for forbidden in ("inbox_processor", "openai", "anthropic", "read_next_actions"):
                self.assertNotIn(forbidden, body, f"{fn_name} must not reference {forbidden}")


class TestTaskCallerTestsHaveHardSocketBlock(unittest.TestCase):

    def test_phase_36d_test_files_registered(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        for filename in ("test_business_task_commands.py", "test_task_caller_ux.py"):
            self.assertIn(filename, conftest_src)


if __name__ == "__main__":
    unittest.main()
