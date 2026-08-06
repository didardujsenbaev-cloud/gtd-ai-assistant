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


def _task_manager_top_level_constructs(src: str) -> dict:
    """Maps a deterministic construct identifier -> exact source text
    for every top-level node in task_manager.py — Import/ImportFrom/
    FunctionDef/AsyncFunctionDef/ClassDef/Assign (single Name target)
    fall into a named category; anything else (module docstring Expr,
    multi-target assignments, etc.) falls into a content-keyed
    fallback category so it is still tracked, not silently ignored.

    Raises ValueError on a duplicate identifier — overwriting one
    construct with another under the same key would hide an
    unauthorized top-level construct instead of surfacing it as a
    guard failure, so a collision must fail loudly rather than pick
    one value arbitrarily. Shared by the real task_manager.py scope
    guard and its own duplicate-identifier tests, so both always
    observe identical collector behavior.
    """
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    out: dict[str, str] = {}

    def _add(key: str, node) -> None:
        if key in out:
            raise ValueError(f"duplicate top-level construct identifier: {key!r} (line {node.lineno})")
        out[key] = "".join(lines[node.lineno - 1:node.end_lineno])

    for node in tree.body:
        text = "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.FunctionDef):
            _add(f"function:{node.name}", node)
        elif isinstance(node, ast.AsyncFunctionDef):
            _add(f"async_function:{node.name}", node)
        elif isinstance(node, ast.ClassDef):
            _add(f"class:{node.name}", node)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            _add(f"assignment:{node.targets[0].id}", node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            _add(f"import:{text.strip()}", node)
        else:
            _add(f"other:{text.strip()[:80]}", node)
    return out


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
        # list_tasks gained a keyword-only raise_on_error parameter for
        # the strict storage-error-contract mode — every other
        # top-level construct in task_manager.py must remain
        # source-identical to HEAD.
        import subprocess

        head_src = subprocess.run(
            ["git", "show", "HEAD:business_core/task_manager.py"],
            cwd=WORKSPACE, capture_output=True, text=True, check=True,
        ).stdout
        current_src = (BUSINESS_CORE / "task_manager.py").read_text(encoding="utf-8")

        head = _task_manager_top_level_constructs(head_src)
        current = _task_manager_top_level_constructs(current_src)
        self.assertEqual(set(current) - set(head), set(), "task_manager.py: unapproved new top-level construct")
        self.assertEqual(set(head) - set(current), set(), "task_manager.py: a top-level construct was removed")
        changed = {k for k in head if head[k] != current[k]}
        self.assertEqual(changed, {"function:list_tasks"}, "task_manager.py: only list_tasks may change this phase")

    _TASK_MANAGER_DUPLICATE_CASES = (
        (
            "duplicate sync function",
            "def foo():\n    pass\n\n\ndef foo():\n    pass\n",
            "function:foo",
        ),
        (
            "duplicate async function",
            "async def foo():\n    pass\n\n\nasync def foo():\n    pass\n",
            "async_function:foo",
        ),
        (
            "duplicate class",
            "class Foo:\n    pass\n\n\nclass Foo:\n    pass\n",
            "class:Foo",
        ),
        (
            "duplicate assignment",
            "X = 1\nX = 2\n",
            "assignment:X",
        ),
    )

    def test_task_manager_collector_rejects_duplicate_identifiers(self):
        # Overwriting a duplicate top-level construct identifier
        # instead of failing would hide an unauthorized second
        # construct sharing the same name behind whichever one
        # happened to be collected last — this must fail loudly
        # instead of picking a value arbitrarily.
        for label, src, expected_key in self._TASK_MANAGER_DUPLICATE_CASES:
            with self.subTest(case=label):
                with self.assertRaises(ValueError) as ctx:
                    _task_manager_top_level_constructs(src)
                self.assertIn(expected_key, str(ctx.exception))

    def test_task_manager_collector_accepts_valid_non_duplicate_source(self):
        src = (
            "import os\n"
            "from pathlib import Path\n"
            "X = 1\n"
            "def foo():\n"
            "    pass\n"
            "async def bar():\n"
            "    pass\n"
            "class Baz:\n"
            "    pass\n"
        )
        constructs = _task_manager_top_level_constructs(src)
        for key in ("import:import os", "import:from pathlib import Path",
                    "assignment:X", "function:foo", "async_function:bar", "class:Baz"):
            self.assertIn(key, constructs)

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

    # COMMAND_ENFORCEMENT_MAP's size and TASK-resource exclusion were
    # true for the unassign_task business-layer hardening phase
    # specifically, before /unassigntask itself was authorized; the
    # current map contract is scoped by
    # TestUnassigntaskHandlerAuthorization below instead.

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
    candidates = [i for i in (src.find("\ndef ", start + 10), src.find("\nasync def ", start + 10)) if i != -1]
    end = min(candidates) if candidates else len(src)
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
# unassigntask_cmd malformed-lookup fail-closed guards.
# ─────────────────────────────────────────────────────────────

class TestUnassigntaskMalformedLookupFailClosed(unittest.TestCase):

    def test_isinstance_dict_check_precedes_first_get(self):
        body = _th_function_body("unassigntask_cmd")
        isinstance_idx = body.index("isinstance(first_task, dict)")
        first_get_idx = body.index('first_task.get(')
        self.assertLess(isinstance_idx, first_get_idx)

    def test_isinstance_dict_check_precedes_second_get(self):
        body = _th_function_body("unassigntask_cmd")
        isinstance_idx = body.index("isinstance(second_task, dict)")
        second_get_idx = body.index('second_task.get(')
        self.assertLess(isinstance_idx, second_get_idx)

    def test_malformed_first_branch_returns_before_authorization(self):
        body = _th_function_body("unassigntask_cmd")
        malformed_idx = body.index("isinstance(first_task, dict)")
        authorize_idx = body.index("_authorize_or_reply(")
        self.assertLess(malformed_idx, authorize_idx)

    def test_malformed_second_branch_returns_before_mutation(self):
        body = _th_function_body("unassigntask_cmd")
        malformed_idx = body.index("isinstance(second_task, dict)")
        mutate_idx = body.index("_mutate_target_in_thread(")
        self.assertLess(malformed_idx, mutate_idx)

    def test_no_broad_dict_coercion(self):
        body = _th_function_body("unassigntask_cmd")
        self.assertNotIn("dict(first_task)", body)
        self.assertNotIn("dict(second_task)", body)

    def test_no_raw_lookup_value_rendering_or_logging(self):
        body = _th_function_body("unassigntask_cmd")
        for forbidden in (
            "str(first_task)", "repr(first_task)", "str(second_task)", "repr(second_task)",
            "type(first_task)", "type(second_task)",
        ):
            self.assertNotIn(forbidden, body)

    def test_no_retry_construct(self):
        body = _th_function_body("unassigntask_cmd")
        for forbidden in ("while True", "for attempt", "range(3)", "retry_count"):
            self.assertNotIn(forbidden, body)

    def test_exactly_two_canonical_lookups_in_source(self):
        body = _th_function_body("unassigntask_cmd")
        self.assertEqual(body.count("_resolve_target_in_thread("), 2)

    def test_no_or_empty_dict_fallback_remains_on_first_lookup(self):
        # The narrow correction replaced (first_task or {}).get(...)
        # with an explicit isinstance check — the old permissive
        # fallback idiom must not reappear.
        body = _th_function_body("unassigntask_cmd")
        self.assertNotIn("(first_task or {})", body)
        self.assertNotIn("(second_task or {})", body)


# ─────────────────────────────────────────────────────────────
# bctask_cmd secure-read-flow guards.
# ─────────────────────────────────────────────────────────────

class TestBctaskSecureReadFlow(unittest.TestCase):

    def test_transport_validation_exists(self):
        body = _th_function_body("bctask_cmd")
        self.assertIn("_validate_bc_transport_or_reply(update)", body)

    def test_allowed_keys_enforced(self):
        body = _th_function_body("bctask_cmd")
        self.assertIn('set(args.keys()) <= {"task_id", "_pos0"}', body)

    def test_lookup_uses_thread_helper(self):
        body = _th_function_body("bctask_cmd")
        self.assertIn("_resolve_target_in_thread(find_task_by_id, task_id)", body)

    def test_exactly_one_canonical_lookup_of_task(self):
        body = _th_function_body("bctask_cmd")
        self.assertEqual(body.count("_resolve_target_in_thread(find_task_by_id"), 1)

    def test_isinstance_dict_check_precedes_get(self):
        body = _th_function_body("bctask_cmd")
        isinstance_idx = body.index("isinstance(task, dict)")
        get_idx = body.index("task.get(")
        self.assertLess(isinstance_idx, get_idx)

    def test_malformed_branch_returns_before_authorization(self):
        body = _th_function_body("bctask_cmd")
        malformed_idx = body.index("isinstance(task, dict)")
        authorize_idx = body.index("_authorize_or_reply(")
        self.assertLess(malformed_idx, authorize_idx)

    def test_authorization_precedes_formatter_call(self):
        body = _th_function_body("bctask_cmd")
        authorize_idx = body.index("_authorize_or_reply(")
        formatter_idx = body.index("_task_detail_lines(")
        self.assertLess(authorize_idx, formatter_idx)

    def test_authorization_uses_task_read(self):
        body = _th_function_body("bctask_cmd")
        self.assertIn('resource="TASK"', body)
        self.assertIn('action="READ"', body)

    def test_no_or_empty_dict_fallback(self):
        body = _th_function_body("bctask_cmd")
        self.assertNotIn("(task or {})", body)

    def test_no_broad_dict_coercion(self):
        body = _th_function_body("bctask_cmd")
        self.assertNotIn("dict(task)", body)

    def test_no_raw_lookup_value_rendering_or_logging(self):
        body = _th_function_body("bctask_cmd")
        for forbidden in ("str(task)", "repr(task)", "type(task)"):
            self.assertNotIn(forbidden, body)

    def test_no_retry_construct(self):
        body = _th_function_body("bctask_cmd")
        for forbidden in ("while True", "for attempt", "range(3)", "retry_count"):
            self.assertNotIn(forbidden, body)

    def test_no_mutation_call(self):
        body = _th_function_body("bctask_cmd")
        for forbidden in ("unassign_task(", "assign_task(", "transition_task_status(", "_mutate_target_in_thread("):
            self.assertNotIn(forbidden, body)

    def test_fixed_literal_exception_logging(self):
        body = _th_function_body("bctask_cmd")
        self.assertIn('log.error("bctask_cmd formatting/reply failure")', body)
        for forbidden in ("str(exc)", "repr(exc)", "f\"bctask_cmd error: {e}\"", "exc_info=True"):
            self.assertNotIn(forbidden, body)

    def test_no_assignment_helper_reference(self):
        body = _th_function_body("bctask_cmd")
        self.assertNotIn("get_current_task_assignment", body)

    def test_no_cache_consistency_helper_reference(self):
        body = _th_function_body("bctask_cmd")
        self.assertNotIn("task_assignment_cache_is_consistent", body)

    def test_no_business_builder_import(self):
        body = _th_function_body("bctask_cmd")
        self.assertNotIn("business_builder", body)

    def test_no_post_authorization_storage_helper_call(self):
        # After authorization succeeds, nothing between that call and
        # the formatter/reply may read storage — the only remaining
        # calls in that span are the formatter and the reply itself.
        body = _th_function_body("bctask_cmd")
        authorize_idx = body.index("_authorize_or_reply(")
        after_authorize_call_end = body.index(":\n        return\n", authorize_idx) + len(":\n        return\n")
        tail = body[after_authorize_call_end:]
        for forbidden in ("_resolve_target_in_thread(", "_mutate_target_in_thread(", "find_task_by_id("):
            self.assertNotIn(forbidden, tail)

    def test_strict_business_id_type_check_precedes_authorization(self):
        body = _th_function_body("bctask_cmd")
        check_idx = body.index("isinstance(business_id_value, str)")
        authorize_idx = body.index("_authorize_or_reply(")
        self.assertLess(check_idx, authorize_idx)

    def test_no_arbitrary_str_conversion_of_business_id(self):
        body = _th_function_body("bctask_cmd")
        self.assertNotIn("str(task.get(\"business_id\"", body)
        self.assertNotIn("str(business_id_value)", body)


# ─────────────────────────────────────────────────────────────
# _task_detail_lines formatter fail-closed guards.
# ─────────────────────────────────────────────────────────────

class TestTaskDetailLinesFormatterSafety(unittest.TestCase):

    def test_isinstance_dict_check_first(self):
        body = _th_bare_function_source("_task_detail_lines")
        self.assertIn("isinstance(task, dict)", body)
        isinstance_idx = body.index("isinstance(task, dict)")
        first_subscript_idx = body.find("task[")
        if first_subscript_idx != -1:
            self.assertLess(isinstance_idx, first_subscript_idx)

    def test_no_direct_subscript_access(self):
        body = _th_bare_function_source("_task_detail_lines")
        self.assertNotIn("task['", body)
        self.assertNotIn('task["', body)

    def test_no_raw_error_rendering(self):
        body = _th_bare_function_source("_task_detail_lines")
        self.assertNotIn('result["error"]', body)
        self.assertNotIn('result.get("error")', body)

    def test_no_str_or_repr_of_arbitrary_input(self):
        body = _th_bare_function_source("_task_detail_lines")
        for forbidden in ("str(task)", "repr(task)"):
            self.assertNotIn(forbidden, body)

    def test_no_assignment_or_cache_output(self):
        body = _th_bare_function_source("_task_detail_lines")
        for forbidden in ("current_assignment", "consistency", "Active Assignment ID", "Assignment cache", "РАССОГЛАСОВАН"):
            self.assertNotIn(forbidden, body)

    def test_no_sheets_telegram_authorization_business_layer_calls(self):
        body = _th_bare_function_source("_task_detail_lines")
        for forbidden in (
            "get_business_sheet(", "read_business_sheet(", "_reply(", "await ",
            "authorize_business_core_access(", "business_builder.", "task_manager.",
        ):
            self.assertNotIn(forbidden, body)

    def test_no_logging_of_task_row(self):
        body = _th_bare_function_source("_task_detail_lines")
        self.assertNotIn("log.", body)

    def test_formatter_does_not_mutate_input(self):
        import copy
        from business_core.telegram_handlers import _task_detail_lines
        task = {"task_id": "TSK-1", "business_id": "BIZ-1", "title": "X", "status": "ready"}
        before = copy.deepcopy(task)
        _task_detail_lines(task)
        self.assertEqual(task, before)

    def test_formatter_never_raises_for_malformed_input(self):
        from business_core.telegram_handlers import _task_detail_lines

        class Poisoned:
            def __str__(self):
                return "STR-SECRET-MARKER"

            def __repr__(self):
                return "REPR-SECRET-MARKER"

        cases = [None, {}, [], "bad", object(), 0, 1, Poisoned(), {"task_id": 123}, {"due_date": Poisoned()}]
        for case in cases:
            with self.subTest(task=repr(case)):
                result = _task_detail_lines(case)
                self.assertIsInstance(result, list)
                joined = "\n".join(result)
                self.assertNotIn("STR-SECRET-MARKER", joined)
                self.assertNotIn("REPR-SECRET-MARKER", joined)


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
# telegram_handlers.py, only bctask_cmd, _task_detail_lines and
# COMMAND_ENFORCEMENT_MAP may differ — no other handler command
# function, registration, or module-level constant changes.
# unassigntask_cmd and _task_assignment_message (each approved to
# differ in an earlier phase) are now source-identical again,
# protected the same as every other function.
# ─────────────────────────────────────────────────────────────

_TELEGRAM_HANDLERS_APPROVED_TO_DIFFER = frozenset({
    "async_function:bctask_cmd", "function:_task_detail_lines",
    "assignment:COMMAND_ENFORCEMENT_MAP",
})

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

    def test_no_other_handler_command_function_changed(self):
        head_src = _git_show_head_telegram_handlers_py()
        current_src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")
        head = _telegram_handlers_top_level_constructs(head_src)
        current = _telegram_handlers_top_level_constructs(current_src)
        for name in ("assigntask_cmd", "reassigntask_cmd", "bctasks_cmd", "unassigntask_cmd", "newbctask_cmd", "updatetask_cmd"):
            key = f"async_function:{name}"
            self.assertIn(key, head)
            self.assertEqual(head[key], current[key], f"{name} must not change this phase")

    def test_task_assignment_message_unchanged_this_phase(self):
        head_src = _git_show_head_telegram_handlers_py()
        current_src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")
        head = _telegram_handlers_top_level_constructs(head_src)
        current = _telegram_handlers_top_level_constructs(current_src)
        self.assertEqual(head["function:_task_assignment_message"], current["function:_task_assignment_message"])

    def test_command_enforcement_map_gains_exactly_one_entry(self):
        # The bctask entry was committed as HEAD itself, so comparing
        # the working tree against HEAD no longer reveals this
        # addition — that transient check is retired here. Durable
        # protection is the exact-value assertions below, plus the
        # exact-value guard in test_command_enforcement.py's
        # test_mutation_entries_exact and the Task-key-set guard in
        # test_authorization_domain.py.
        import business_core.telegram_handlers as th
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 16)
        self.assertIn("bctask", th.COMMAND_ENFORCEMENT_MAP)
        self.assertEqual(
            th.COMMAND_ENFORCEMENT_MAP["bctask"],
            {
                "resource": "TASK", "action": "READ", "target_shape": "BUSINESS",
                "operation_kind": "READ", "requires_fresh_reread": False,
            },
        )
        self.assertNotIn("bctasks", th.COMMAND_ENFORCEMENT_MAP)

        # Committed in an earlier phase, not this one — still present
        # and unchanged.
        self.assertIn("unassigntask", th.COMMAND_ENFORCEMENT_MAP)
        self.assertEqual(
            th.COMMAND_ENFORCEMENT_MAP["unassigntask"],
            {
                "resource": "TASK", "action": "ASSIGN", "target_shape": "BUSINESS",
                "operation_kind": "MUTATION", "requires_fresh_reread": True,
                "mutation_side_effect_class": "MULTI_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
            },
        )

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
        "async def unassigntask_cmd(update, context):\n"
        "    return None\n"
    )

    def _diff(self, modified_src: str, approved=frozenset({"async_function:unassigntask_cmd", "assignment:COMMAND_ENFORCEMENT_MAP"})):
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
        modified = self._BASELINE.replace(
            "def _task_assignment_message(result, task_id):\n    return task_id",
            "def _task_assignment_message(result, task_id):\n    return task_id + '!'",
        )
        removed, added, changed = self._diff(modified)
        self.assertIn("function:_task_assignment_message", changed)

    def test_command_enforcement_map_change_permitted(self):
        modified = self._BASELINE.replace("COMMAND_ENFORCEMENT_MAP = {}", 'COMMAND_ENFORCEMENT_MAP = {"unassigntask": {}}')
        removed, added, changed = self._diff(modified)
        self.assertEqual(removed, set())
        self.assertEqual(added, set())
        self.assertNotIn("assignment:COMMAND_ENFORCEMENT_MAP", changed)

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
        modified = self._BASELINE.replace(
            "\ndef _task_assignment_message(result, task_id):\n    return task_id\n", "\n",
        )
        removed, added, changed = self._diff(modified)
        self.assertIn("function:_task_assignment_message", removed)

    def test_unexpected_new_function_detected(self):
        modified = self._BASELINE + "\nasync def sneaky_cmd(update, context):\n    return None\n"
        removed, added, changed = self._diff(modified)
        self.assertIn("async_function:sneaky_cmd", added)

    def test_rename_detected_as_removal_plus_addition(self):
        modified = self._BASELINE.replace(
            "def _task_assignment_message(result, task_id):", "def _renamed_message(result, task_id):",
        )
        removed, added, changed = self._diff(modified)
        self.assertIn("function:_task_assignment_message", removed)
        self.assertIn("function:_renamed_message", added)

    def test_unassigntask_cmd_change_is_permitted(self):
        modified = self._BASELINE.replace(
            "async def unassigntask_cmd(update, context):\n    return None",
            "async def unassigntask_cmd(update, context):\n    return 1",
        )
        removed, added, changed = self._diff(modified)
        self.assertEqual(removed, set())
        self.assertEqual(added, set())
        self.assertNotIn("async_function:unassigntask_cmd", changed)

    def test_second_new_handler_command_rejected(self):
        modified = self._BASELINE + "\nasync def assigntask_cmd(update, context):\n    return None\n"
        removed, added, changed = self._diff(modified)
        self.assertIn("async_function:assigntask_cmd", added)

    def test_duplicate_construct_identifier_fails_explicitly(self):
        duplicate_src = self._BASELINE + "\nCOMMAND_ENFORCEMENT_MAP = {}\n"
        with self.assertRaises(ValueError):
            _telegram_handlers_top_level_constructs(duplicate_src)


if __name__ == "__main__":
    unittest.main()
