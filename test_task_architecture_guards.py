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


# ─────────────────────────────────────────────────────────────
# Phase 18A.4-H0: unassign_task partial-state hardening guards.
# ─────────────────────────────────────────────────────────────

def _bb_function_body(fn_name: str) -> str:
    path = BUSINESS_CORE / "business_builder.py"
    src = path.read_text(encoding="utf-8")
    start = src.index(f"def {fn_name}(")
    end = src.index("\ndef ", start + 10)
    return src[start:end]


class TestUnassignTaskPartialStateHardening(unittest.TestCase):

    def test_only_unassign_task_changed_in_business_builder(self):
        """Confined-diff guard: every business_builder.py line the
        working tree adds relative to HEAD must fall strictly inside
        unassign_task's own body — no other Task (or non-Task) function
        in this file may differ."""
        import subprocess
        diff = subprocess.run(
            ["git", "diff", "--unified=0", "HEAD", "--", "business_core/business_builder.py"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout
        if not diff:
            self.skipTest("no working-tree diff against HEAD for business_builder.py")
        body = _bb_function_body("unassign_task")
        body_lines = {line for line in body.splitlines() if line.strip()}
        for line in diff.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            content = line[1:]
            if not content.strip():
                continue
            self.assertIn(
                content, body_lines,
                f"business_builder.py added line falls outside unassign_task: {content!r}",
            )

    def test_task_manager_unchanged(self):
        import subprocess
        diff = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/task_manager.py"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(diff.strip(), "")

    # telegram_handlers.py zero-diff was true for the unassign_task
    # business-layer hardening phase specifically; ongoing
    # telegram_handlers.py changes (e.g. the Task assignment mapper
    # hardening) are scoped by TestTelegramHandlersTopLevelConstructGuard
    # below instead.

    def test_authorization_unchanged(self):
        import subprocess
        diff = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/authorization.py"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(diff.strip(), "")

    def test_command_enforcement_map_still_size_14_and_no_task_entry(self):
        import business_core.telegram_handlers as th
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 14)
        for name, spec in th.COMMAND_ENFORCEMENT_MAP.items():
            self.assertNotEqual(spec.get("resource"), "TASK", f"{name} must not be wired to resource=TASK")

    def test_unassigntask_command_not_newly_authorized(self):
        import business_core.telegram_handlers as th
        self.assertNotIn("unassigntask", th.COMMAND_ENFORCEMENT_MAP)

    # The mapper's raw-error fallback wording asserted here was true
    # before the mapper itself was hardened; _task_assignment_message's
    # new safe-fallback contract is covered by
    # TestTaskAssignmentMessageMapperHardening below instead.

    def test_write_order_assignment_end_then_cache_clear(self):
        body = _bb_function_body("unassign_task")
        self.assertLess(body.index("end_task_assignment("), body.index("update_task_assignment_cache("))

    def test_cache_result_ok_is_explicitly_checked(self):
        body = _bb_function_body("unassign_task")
        self.assertIn('cache_result.get("ok", False)', body)

    def test_partial_state_code_exists(self):
        body = _bb_function_body("unassign_task")
        self.assertIn("TASK_UNASSIGNMENT_PARTIAL_FAILURE", body)

    def test_partial_state_retry_safe_is_explicitly_false(self):
        body = _bb_function_body("unassign_task")
        partial_start = body.index("TASK_UNASSIGNMENT_PARTIAL_FAILURE")
        partial_block = body[partial_start:partial_start + 500]
        self.assertIn("retry_safe=False", partial_block)

    def test_no_raw_cache_error_copied_into_result(self):
        body = _bb_function_body("unassign_task")
        code_lines = [line for line in body.splitlines() if line.strip() and not line.strip().startswith("#")]
        code_only = "\n".join(code_lines)
        self.assertNotIn("error=cache_result", code_only)
        self.assertNotIn('cache_result.get("error")', code_only)
        self.assertNotIn('cache_result["error"]', code_only)

    def test_no_retry_construct_added(self):
        body = _bb_function_body("unassign_task")
        for forbidden in ("while True", "for attempt", "range(3)", "retry_count"):
            self.assertNotIn(forbidden, body)

    def test_no_direct_telegram_reply_logic(self):
        body = _bb_function_body("unassign_task")
        for forbidden in ("update.message.reply", "_reply(", "await "):
            self.assertNotIn(forbidden, body)

    def test_no_new_direct_sheets_write_introduced(self):
        body = _bb_function_body("unassign_task")
        for forbidden in ("update_cell(", "append_business_row(", "batch_append_business_rows("):
            self.assertNotIn(forbidden, body)


# ─────────────────────────────────────────────────────────────
# _task_assignment_message mapper hardening guards.
# ─────────────────────────────────────────────────────────────

def _th_bare_function_source(fn_name: str) -> str:
    path = BUSINESS_CORE / "telegram_handlers.py"
    src = path.read_text(encoding="utf-8")
    start = src.index(f"def {fn_name}(")
    end = src.index("\ndef ", start + 10)
    return src[start:end]


def _th_function_code_only(fn_name: str) -> str:
    """Same as _th_bare_function_source() but with the leading
    docstring stripped, so guard assertions inspect only executable
    code — the docstring itself intentionally names the exact
    forbidden patterns (result["error"], business_builder.assign_task,
    etc.) as prose explaining what the function avoids doing."""
    full = _th_bare_function_source(fn_name)
    first = full.find('"""')
    if first == -1:
        return full
    second = full.find('"""', first + 3)
    if second == -1:
        return full
    return full[:first] + full[second + 3:]


class TestTaskAssignmentMessageMapperHardening(unittest.TestCase):

    def test_no_result_get_error_rendering(self):
        body = _th_function_code_only("_task_assignment_message")
        self.assertNotIn('result.get("error")', body)
        self.assertNotIn("result.get('error')", body)

    def test_no_direct_result_error_subscript_rendering(self):
        body = _th_function_code_only("_task_assignment_message")
        self.assertNotIn('result["error"]', body)
        self.assertNotIn("result['error']", body)

    def test_no_str_or_repr_of_result(self):
        body = _th_function_code_only("_task_assignment_message")
        self.assertNotIn("str(result)", body)
        self.assertNotIn("repr(result)", body)

    def test_no_telegram_send_or_reply_call(self):
        body = _th_function_code_only("_task_assignment_message")
        for forbidden in ("_reply(", "await ", "send_message(", "bot.send"):
            self.assertNotIn(forbidden, body)

    def test_no_sheets_or_business_layer_call(self):
        body = _th_function_code_only("_task_assignment_message")
        for forbidden in ("get_business_sheet(", "read_business_sheet(", "business_builder.", "task_manager.", "update_cell(", "append_business_row("):
            self.assertNotIn(forbidden, body)

    def test_has_explicit_partial_state_branch(self):
        body = _th_function_code_only("_task_assignment_message")
        self.assertIn('code == "TASK_UNASSIGNMENT_PARTIAL_FAILURE"', body)

    def test_has_distinct_noop_and_changed_success_handling(self):
        body = _th_function_code_only("_task_assignment_message")
        self.assertIn('result.get("changed") is True', body)
        self.assertIn('result.get("changed") is False', body)

    def test_strict_ok_is_true_identity_check_exists(self):
        body = _th_function_code_only("_task_assignment_message")
        self.assertIn("ok is True", body)
        self.assertIn("ok is not True", body)

    def test_no_retry_loop(self):
        body = _th_function_code_only("_task_assignment_message")
        for forbidden in ("while True", "for attempt", "range(3)", "retry_count"):
            self.assertNotIn(forbidden, body)

    def test_no_raw_exception_logging(self):
        body = _th_function_code_only("_task_assignment_message")
        log_lines = [line for line in body.splitlines() if "log.warning(" in line or "log.error(" in line]
        for line in log_lines:
            self.assertNotIn("error", line.split("f\"")[-1] if 'f"' in line else line)
            self.assertNotIn("exc", line)

    def test_no_result_dict_mutation_construct(self):
        body = _th_function_code_only("_task_assignment_message")
        for forbidden in ("result[", "result.update(", "result.pop(", "result.setdefault(", "del result"):
            # result["error"]/result['error'] already covered above as a
            # read; the only bracket-subscript writes would look like
            # result["x"] = ... — none exist, since result is never
            # assigned into.
            if forbidden == "result[":
                self.assertNotIn("result[", body.replace('result.get("', '').replace("result.get('", ''))
            else:
                self.assertNotIn(forbidden, body)

    def test_generic_fallback_does_not_interpolate_code(self):
        body = _th_function_code_only("_task_assignment_message")
        non_log_lines = "\n".join(
            line for line in body.splitlines()
            if "log.warning(" not in line and "log.error(" not in line
        )
        for forbidden in ("{code", "(code ", "(code)", "code!r", "code or "):
            self.assertNotIn(forbidden, non_log_lines)

    def test_no_input_derived_token_interpolation_outside_known_branches(self):
        """The only f-string interpolations anywhere in the function
        must reference task_id or an already-approved structured field
        (assignment_id/previous_assignment_id/conflicting_assignment_ids)
        inside one of the explicit known-code branches — never code,
        error, or any other raw result field, and never inside the
        generic-fallback return itself."""
        body = _th_function_code_only("_task_assignment_message")
        generic_line = 'return generic_failure'
        self.assertIn(generic_line, body)
        # Every occurrence of the fixed return must be a bare return of
        # the local variable, never an f-string built from result data.
        for line in body.splitlines():
            if "generic_failure" in line and "return" in line:
                self.assertNotIn("f\"", line)
                self.assertNotIn("f'", line)

    def test_generic_failure_literal_is_function_local_not_module_level(self):
        full_src = _th_bare_function_source("_task_assignment_message")
        self.assertIn('generic_failure = "', full_src)
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("def _task_assignment_message(")
        module_level_prefix = src[:start]
        self.assertNotIn("_TASK_ASSIGNMENT_GENERIC_FAILURE", module_level_prefix)
        self.assertNotIn("_TASK_ASSIGNMENT_GENERIC_FAILURE", src)


# ─────────────────────────────────────────────────────────────
# business_builder.py comprehensive top-level construct guard.
#
# Complements TestPhase17E2A4H1OfferHardeningScope in
# test_command_enforcement.py (a function-level allowlist covering
# only function bodies) with source-identity protection for every
# other top-level construct in business_builder.py — imports, module-
# level assignments/annotated-assignments, and classes — none of
# which the function-level guard inspects. Together the two guards
# prove the entire module is unchanged except for one approved
# function.
# ─────────────────────────────────────────────────────────────

_BUSINESS_BUILDER_APPROVED_TO_DIFFER = frozenset({"function:unassign_task"})

_BUSINESS_BUILDER_KNOWN_BENIGN_TOP_LEVEL_NODE_TYPES = (ast.Expr, ast.Pass)


def _business_builder_target_names(target) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_business_builder_target_names(elt))
        return names
    if isinstance(target, ast.Starred):
        return _business_builder_target_names(target.value)
    return [f"<non_name_target:{ast.dump(target)}>"]


def _business_builder_top_level_constructs(src: str) -> dict:
    """Maps a deterministic construct identifier -> exact source text
    for every top-level Import/ImportFrom/FunctionDef/AsyncFunctionDef/
    ClassDef/Assign/AnnAssign in a module, sliced by lineno/end_lineno.
    Raises ValueError if two constructs resolve to the same identifier
    — silently overwriting one would hide a real defect instead of
    surfacing it as a guard failure."""
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    out: dict[str, str] = {}

    def _add(key: str, node) -> None:
        if key in out:
            raise ValueError(f"duplicate top-level construct identifier: {key!r} (line {node.lineno})")
        out[key] = "".join(lines[node.lineno - 1:node.end_lineno])

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            _add(f"function:{node.name}", node)
        elif isinstance(node, ast.AsyncFunctionDef):
            _add(f"async_function:{node.name}", node)
        elif isinstance(node, ast.ClassDef):
            _add(f"class:{node.name}", node)
        elif isinstance(node, ast.Assign):
            names = []
            for t in node.targets:
                names.extend(_business_builder_target_names(t))
            _add("assignment:" + ",".join(sorted(names)), node)
        elif isinstance(node, ast.AnnAssign):
            names = _business_builder_target_names(node.target)
            _add("annassign:" + ",".join(sorted(names)), node)
        elif isinstance(node, ast.Import):
            parts = sorted(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
            _add("import:" + ",".join(parts), node)
        elif isinstance(node, ast.ImportFrom):
            parts = sorted(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
            module = ("." * (node.level or 0)) + (node.module or "")
            _add(f"import_from:{module}:" + ",".join(parts), node)
        # Everything else (module docstring Expr, bare Pass, etc.) is
        # intentionally not construct-identified here — it is still
        # proven accounted-for by
        # test_exhaustive_top_level_node_coverage below, which fails
        # explicitly if any top-level node type is neither one of the
        # categories handled above nor an explicitly known-benign type.
    return out


def _git_show_head_business_builder_py() -> str:
    import subprocess
    result = subprocess.run(
        ["git", "show", "HEAD:business_core/business_builder.py"],
        cwd=WORKSPACE, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"git show HEAD:business_core/business_builder.py failed: {result.stderr}")
    return result.stdout


class TestBusinessBuilderTopLevelConstructGuard(unittest.TestCase):

    def test_only_approved_construct_differs(self):
        head_src = _git_show_head_business_builder_py()
        current_src = (BUSINESS_CORE / "business_builder.py").read_text(encoding="utf-8")

        head = _business_builder_top_level_constructs(head_src)
        current = _business_builder_top_level_constructs(current_src)

        removed = set(head) - set(current)
        added = set(current) - set(head)
        self.assertEqual(removed, set(), f"business_builder.py: construct(s) removed: {sorted(removed)}")
        self.assertEqual(added, set(), f"business_builder.py: unexpected new construct(s): {sorted(added)}")

        for key in head:
            if key in _BUSINESS_BUILDER_APPROVED_TO_DIFFER:
                continue
            self.assertEqual(
                head[key], current[key],
                f"business_builder.py: unapproved construct changed: {key!r} — only "
                f"{sorted(_BUSINESS_BUILDER_APPROVED_TO_DIFFER)} may differ this phase",
            )

    def test_unassign_task_construct_present_in_both_versions(self):
        head_src = _git_show_head_business_builder_py()
        current_src = (BUSINESS_CORE / "business_builder.py").read_text(encoding="utf-8")
        head = _business_builder_top_level_constructs(head_src)
        current = _business_builder_top_level_constructs(current_src)
        self.assertIn("function:unassign_task", head)
        self.assertIn("function:unassign_task", current)

    def test_exhaustive_top_level_node_coverage(self):
        head_src = _git_show_head_business_builder_py()
        tree = ast.parse(head_src)
        constructs = _business_builder_top_level_constructs(head_src)
        accounted_count = 0
        unaccounted_types = []
        for node in tree.body:
            if isinstance(node, (
                ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom,
            )):
                accounted_count += 1
            elif isinstance(node, _BUSINESS_BUILDER_KNOWN_BENIGN_TOP_LEVEL_NODE_TYPES):
                continue
            else:
                unaccounted_types.append(type(node).__name__)
        self.assertEqual(unaccounted_types, [], f"business_builder.py has unprotected top-level node type(s): {unaccounted_types}")
        self.assertEqual(accounted_count, len(constructs))

    def test_no_duplicate_construct_identifiers_in_real_source(self):
        # _business_builder_top_level_constructs() itself raises
        # ValueError on a duplicate — this proves the real HEAD source
        # does not already contain one (a raise here would fail the
        # test with a traceback, which is the desired explicit signal).
        head_src = _git_show_head_business_builder_py()
        _business_builder_top_level_constructs(head_src)


class TestBusinessBuilderConstructGuardHelperUnit(unittest.TestCase):
    """Synthetic negative tests for
    _business_builder_top_level_constructs() and its identity-
    comparison usage — proves the guard actually detects each
    mutation class, using only in-memory source strings. Never reads
    or writes business_builder.py on disk."""

    _BASELINE = (
        "import os\n"
        "from collections import OrderedDict\n"
        "\n"
        "CONST_A = 1\n"
        "\n"
        "class Foo:\n"
        "    pass\n"
        "\n"
        "def unassign_task(x):\n"
        "    return x\n"
        "\n"
        "def other_function(y):\n"
        "    return y\n"
    )

    def _diff(self, modified_src: str, approved=frozenset({"function:unassign_task"})):
        head = _business_builder_top_level_constructs(self._BASELINE)
        current = _business_builder_top_level_constructs(modified_src)
        removed = set(head) - set(current)
        added = set(current) - set(head)
        changed = {
            key for key in head
            if key in current and key not in approved and head[key] != current[key]
        }
        return removed, added, changed

    def test_unrelated_function_change_detected(self):
        modified = self._BASELINE.replace("return y", "return y + 1")
        removed, added, changed = self._diff(modified)
        self.assertIn("function:other_function", changed)

    def test_module_constant_change_detected(self):
        modified = self._BASELINE.replace("CONST_A = 1", "CONST_A = 2")
        removed, added, changed = self._diff(modified)
        self.assertIn("assignment:CONST_A", changed)

    def test_import_change_detected(self):
        modified = self._BASELINE.replace("import os", "import sys")
        removed, added, changed = self._diff(modified)
        self.assertIn("import:os", removed)
        self.assertIn("import:sys", added)

    def test_class_change_detected(self):
        modified = self._BASELINE.replace("class Foo:\n    pass", "class Foo:\n    x = 1")
        removed, added, changed = self._diff(modified)
        self.assertIn("class:Foo", changed)

    def test_removal_detected(self):
        modified = self._BASELINE.replace("\ndef other_function(y):\n    return y\n", "\n")
        removed, added, changed = self._diff(modified)
        self.assertIn("function:other_function", removed)

    def test_unexpected_new_function_detected(self):
        modified = self._BASELINE + "\ndef sneaky():\n    pass\n"
        removed, added, changed = self._diff(modified)
        self.assertIn("function:sneaky", added)

    def test_rename_detected_as_removal_plus_addition(self):
        modified = self._BASELINE.replace("def other_function(y):", "def renamed_function(y):")
        removed, added, changed = self._diff(modified)
        self.assertIn("function:other_function", removed)
        self.assertIn("function:renamed_function", added)

    def test_unassign_task_change_is_permitted(self):
        modified = self._BASELINE.replace(
            "def unassign_task(x):\n    return x", "def unassign_task(x):\n    return x + 1",
        )
        removed, added, changed = self._diff(modified)
        self.assertEqual(removed, set())
        self.assertEqual(added, set())
        self.assertNotIn("function:unassign_task", changed)

    def test_second_approved_looking_task_function_rejected(self):
        modified = self._BASELINE + "\ndef assign_task(z):\n    return z\n"
        removed, added, changed = self._diff(modified)
        # A brand-new Task-named function is an unapproved addition —
        # never silently allowed through name-pattern matching. The
        # real guard test asserts added == set() unconditionally, so
        # this addition would fail it regardless of the name chosen.
        self.assertIn("function:assign_task", added)

    def test_duplicate_construct_identifier_fails_explicitly(self):
        duplicate_src = self._BASELINE + "\nCONST_A = 3\n"
        with self.assertRaises(ValueError):
            _business_builder_top_level_constructs(duplicate_src)


# ─────────────────────────────────────────────────────────────
# telegram_handlers.py comprehensive top-level construct guard
# (mirrors the business_builder.py guard above — see that section's
# comment for the rationale). Proves that of every top-level Import/
# ImportFrom/FunctionDef/AsyncFunctionDef/ClassDef/Assign/AnnAssign in
# telegram_handlers.py, only _task_assignment_message may differ —
# no handler command function, registration, or module-level constant
# (including COMMAND_ENFORCEMENT_MAP) changes.
# ─────────────────────────────────────────────────────────────

_TELEGRAM_HANDLERS_APPROVED_TO_DIFFER = frozenset({"function:_task_assignment_message"})

_TELEGRAM_HANDLERS_KNOWN_BENIGN_TOP_LEVEL_NODE_TYPES = (ast.Expr, ast.Pass)


def _telegram_handlers_target_names(target) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_telegram_handlers_target_names(elt))
        return names
    if isinstance(target, ast.Starred):
        return _telegram_handlers_target_names(target.value)
    return [f"<non_name_target:{ast.dump(target)}>"]


def _telegram_handlers_top_level_constructs(src: str) -> dict:
    """Same construct-identity scheme as
    _business_builder_top_level_constructs(), applied to
    telegram_handlers.py — kept as a separate function (rather than a
    shared generic helper) so each guard's already-approved,
    previously-committed sibling implementation stays untouched."""
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    out: dict[str, str] = {}

    def _add(key: str, node) -> None:
        if key in out:
            raise ValueError(f"duplicate top-level construct identifier: {key!r} (line {node.lineno})")
        out[key] = "".join(lines[node.lineno - 1:node.end_lineno])

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            _add(f"function:{node.name}", node)
        elif isinstance(node, ast.AsyncFunctionDef):
            _add(f"async_function:{node.name}", node)
        elif isinstance(node, ast.ClassDef):
            _add(f"class:{node.name}", node)
        elif isinstance(node, ast.Assign):
            names = []
            for t in node.targets:
                names.extend(_telegram_handlers_target_names(t))
            _add("assignment:" + ",".join(sorted(names)), node)
        elif isinstance(node, ast.AnnAssign):
            names = _telegram_handlers_target_names(node.target)
            _add("annassign:" + ",".join(sorted(names)), node)
        elif isinstance(node, ast.Import):
            parts = sorted(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
            _add("import:" + ",".join(parts), node)
        elif isinstance(node, ast.ImportFrom):
            parts = sorted(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
            module = ("." * (node.level or 0)) + (node.module or "")
            _add(f"import_from:{module}:" + ",".join(parts), node)
        # Everything else is proven accounted-for by
        # test_telegram_handlers_exhaustive_top_level_node_coverage
        # below, exactly as for business_builder.py's guard.
    return out


def _git_show_head_telegram_handlers_py() -> str:
    import subprocess
    result = subprocess.run(
        ["git", "show", "HEAD:business_core/telegram_handlers.py"],
        cwd=WORKSPACE, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"git show HEAD:business_core/telegram_handlers.py failed: {result.stderr}")
    return result.stdout


class TestTelegramHandlersTopLevelConstructGuard(unittest.TestCase):

    def test_only_approved_construct_differs(self):
        head_src = _git_show_head_telegram_handlers_py()
        current_src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")

        head = _telegram_handlers_top_level_constructs(head_src)
        current = _telegram_handlers_top_level_constructs(current_src)

        removed = set(head) - set(current)
        added = set(current) - set(head)
        self.assertEqual(removed, set(), f"telegram_handlers.py: construct(s) removed: {sorted(removed)}")
        self.assertEqual(added, set(), f"telegram_handlers.py: unexpected new construct(s): {sorted(added)}")

        for key in head:
            if key in _TELEGRAM_HANDLERS_APPROVED_TO_DIFFER:
                continue
            self.assertEqual(
                head[key], current[key],
                f"telegram_handlers.py: unapproved construct changed: {key!r} — only "
                f"{sorted(_TELEGRAM_HANDLERS_APPROVED_TO_DIFFER)} may differ this phase",
            )

    def test_no_new_top_level_construct_added(self):
        head_src = _git_show_head_telegram_handlers_py()
        current_src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")
        head = _telegram_handlers_top_level_constructs(head_src)
        current = _telegram_handlers_top_level_constructs(current_src)
        added = set(current) - set(head)
        self.assertEqual(added, set())

    def test_task_assignment_message_construct_present_in_both_versions(self):
        head_src = _git_show_head_telegram_handlers_py()
        current_src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")
        head = _telegram_handlers_top_level_constructs(head_src)
        current = _telegram_handlers_top_level_constructs(current_src)
        self.assertIn("function:_task_assignment_message", head)
        self.assertIn("function:_task_assignment_message", current)

    def test_no_handler_command_function_changed(self):
        head_src = _git_show_head_telegram_handlers_py()
        current_src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")
        head = _telegram_handlers_top_level_constructs(head_src)
        current = _telegram_handlers_top_level_constructs(current_src)
        for name in ("assigntask_cmd", "reassigntask_cmd", "unassigntask_cmd", "bctasks_cmd", "bctask_cmd", "newbctask_cmd", "updatetask_cmd"):
            key = f"async_function:{name}"
            self.assertIn(key, head)
            self.assertEqual(head[key], current[key], f"{name} must not change this phase")

    def test_command_enforcement_map_construct_unchanged(self):
        head_src = _git_show_head_telegram_handlers_py()
        current_src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")
        head = _telegram_handlers_top_level_constructs(head_src)
        current = _telegram_handlers_top_level_constructs(current_src)
        self.assertIn("assignment:COMMAND_ENFORCEMENT_MAP", head)
        self.assertEqual(head["assignment:COMMAND_ENFORCEMENT_MAP"], current["assignment:COMMAND_ENFORCEMENT_MAP"])

    def test_telegram_handlers_exhaustive_top_level_node_coverage(self):
        head_src = _git_show_head_telegram_handlers_py()
        tree = ast.parse(head_src)
        constructs = _telegram_handlers_top_level_constructs(head_src)
        accounted_count = 0
        unaccounted_types = []
        for node in tree.body:
            if isinstance(node, (
                ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom,
            )):
                accounted_count += 1
            elif isinstance(node, _TELEGRAM_HANDLERS_KNOWN_BENIGN_TOP_LEVEL_NODE_TYPES):
                continue
            else:
                unaccounted_types.append(type(node).__name__)
        self.assertEqual(unaccounted_types, [], f"telegram_handlers.py has unprotected top-level node type(s): {unaccounted_types}")
        self.assertEqual(accounted_count, len(constructs))

    def test_no_duplicate_construct_identifiers_in_real_source(self):
        head_src = _git_show_head_telegram_handlers_py()
        _telegram_handlers_top_level_constructs(head_src)


class TestTelegramHandlersConstructGuardHelperUnit(unittest.TestCase):
    """Synthetic negative tests for
    _telegram_handlers_top_level_constructs() — same coverage as the
    business_builder.py helper unit tests, using only in-memory source
    strings. Never reads or writes telegram_handlers.py on disk."""

    _BASELINE = (
        "import os\n"
        "from collections import OrderedDict\n"
        "\n"
        "COMMAND_ENFORCEMENT_MAP = {}\n"
        "\n"
        "class Foo:\n"
        "    pass\n"
        "\n"
        "def _task_assignment_message(result, task_id):\n"
        "    return task_id\n"
        "\n"
        "async def assigntask_cmd(update, context):\n"
        "    return None\n"
    )

    def _diff(self, modified_src: str, approved=frozenset({"function:_task_assignment_message"})):
        head = _telegram_handlers_top_level_constructs(self._BASELINE)
        current = _telegram_handlers_top_level_constructs(modified_src)
        removed = set(head) - set(current)
        added = set(current) - set(head)
        changed = {
            key for key in head
            if key in current and key not in approved and head[key] != current[key]
        }
        return removed, added, changed

    def test_unrelated_handler_change_detected(self):
        modified = self._BASELINE.replace("return None", "return 1")
        removed, added, changed = self._diff(modified)
        self.assertIn("async_function:assigntask_cmd", changed)

    def test_command_enforcement_map_change_detected(self):
        modified = self._BASELINE.replace("COMMAND_ENFORCEMENT_MAP = {}", 'COMMAND_ENFORCEMENT_MAP = {"unassigntask": {}}')
        removed, added, changed = self._diff(modified)
        self.assertIn("assignment:COMMAND_ENFORCEMENT_MAP", changed)

    def test_import_change_detected(self):
        modified = self._BASELINE.replace("import os", "import sys")
        removed, added, changed = self._diff(modified)
        self.assertIn("import:os", removed)
        self.assertIn("import:sys", added)

    def test_class_change_detected(self):
        modified = self._BASELINE.replace("class Foo:\n    pass", "class Foo:\n    x = 1")
        removed, added, changed = self._diff(modified)
        self.assertIn("class:Foo", changed)

    def test_removal_detected(self):
        modified = self._BASELINE.replace("\nasync def assigntask_cmd(update, context):\n    return None\n", "\n")
        removed, added, changed = self._diff(modified)
        self.assertIn("async_function:assigntask_cmd", removed)

    def test_unexpected_new_function_detected(self):
        modified = self._BASELINE + "\nasync def sneaky_cmd(update, context):\n    return None\n"
        removed, added, changed = self._diff(modified)
        self.assertIn("async_function:sneaky_cmd", added)

    def test_rename_detected_as_removal_plus_addition(self):
        modified = self._BASELINE.replace("async def assigntask_cmd(", "async def renamed_cmd(")
        removed, added, changed = self._diff(modified)
        self.assertIn("async_function:assigntask_cmd", removed)
        self.assertIn("async_function:renamed_cmd", added)

    def test_task_assignment_message_change_is_permitted(self):
        modified = self._BASELINE.replace(
            "def _task_assignment_message(result, task_id):\n    return task_id",
            "def _task_assignment_message(result, task_id):\n    return task_id + '!'",
        )
        removed, added, changed = self._diff(modified)
        self.assertEqual(removed, set())
        self.assertEqual(added, set())
        self.assertNotIn("function:_task_assignment_message", changed)

    def test_second_new_handler_command_rejected(self):
        modified = self._BASELINE + "\nasync def unassigntask_cmd(update, context):\n    return None\n"
        removed, added, changed = self._diff(modified)
        self.assertIn("async_function:unassigntask_cmd", added)

    def test_duplicate_construct_identifier_fails_explicitly(self):
        duplicate_src = self._BASELINE + "\nCOMMAND_ENFORCEMENT_MAP = {}\n"
        with self.assertRaises(ValueError):
            _telegram_handlers_top_level_constructs(duplicate_src)


if __name__ == "__main__":
    unittest.main()
