"""
Phase 31D incident regression guard (PRS-003).

A real Person row was created in production PEOPLE_REGISTRY because a
/newclient test's mocks targeted the RETIRED call sites
(business_builder.find_existing_person/provision_client_drive/
update_person_drive_info) instead of the ones newclient_confirm()
actually calls post-migration. This meta-test statically scans every
test file that invokes newclient_confirm() and asserts each invocation
site is fully isolated from production, via one of two legitimate
strategies:

  (A) Full sheet-level isolation — mocking
      business_core.sheets.get_business_sheet (as
      test_business_newclient_headersafe.py / test_business_newclient_
      state_snapshot.py do, with a stateful fake sheet). Every
      person_manager function can then run for real and still never
      reach production, because the Sheets client itself is fake.
  (B) Call-point isolation, SCOPED to what that test's mocked
      resolve_person_identity() status can actually reach:
        - "not_found"              -> create_person, update_person,
                                       provision_client_drive_safe
        - "single_match"           -> ensure_client_role,
                                       append_person_biz_id,
                                       provision_client_drive_safe
        - "ambiguous"/"archived_match" -> nothing further (must be a
                                       zero-write branch)
        - status not statically determined -> ALL of
          REQUIRED_MOCK_TARGETS (fail safe to the strictest bar)
      resolve_person_identity() itself must ALWAYS be mocked under
      strategy (B) — its absence was the actual root cause of PRS-003
      (a real scan against production data returned a real, unexpected
      "not_found", which then drove real writes).

This is a static, source-level check (AST), not a live test run — it
makes the mistake structurally impossible to reintroduce silently.
It intentionally does NOT try to resolve call-site indirection through
non-"test_"-named helper methods (e.g. headersafe.py's
_run_newclient_confirm(), state_snapshot.py's _confirm_with_mocks()) —
those helpers are themselves checked directly wherever they contain the
invocation, and every "test_" method that only calls such a helper
inherits that helper's isolation. This guard is deliberately paired
with conftest.py's hard, mock-independent socket-level block, which is
the real backstop: even a test this guard cannot fully analyze can
never reach production, because a live socket connection raises
immediately.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent

SHEET_LEVEL_TARGET = "business_core.sheets.get_business_sheet"

REQUIRED_MOCK_TARGETS = frozenset({
    "business_core.person_manager.resolve_person_identity",
    "business_core.person_manager.create_person",
    "business_core.person_manager.update_person",
    "business_core.person_manager.ensure_client_role",
    "business_core.person_manager.append_person_biz_id",
    "business_core.person_manager.update_person_drive_info",
    "business_core.business_builder.provision_client_drive_safe",
})

_STATUS_REQUIREMENTS = {
    "not_found": {
        "business_core.person_manager.resolve_person_identity",
        "business_core.person_manager.create_person",
        "business_core.person_manager.update_person",
        "business_core.business_builder.provision_client_drive_safe",
    },
    "single_match": {
        "business_core.person_manager.resolve_person_identity",
        "business_core.person_manager.ensure_client_role",
        "business_core.person_manager.append_person_biz_id",
        "business_core.business_builder.provision_client_drive_safe",
    },
    "ambiguous": {"business_core.person_manager.resolve_person_identity"},
    "archived_match": {"business_core.person_manager.resolve_person_identity"},
}

# Files known to actually invoke newclient_confirm() (not just mention
# it in a comment/docstring), anywhere in their source — including
# inside non-"test_"-named helper methods. New files exercising
# newclient_confirm() must be added here — that is itself a deliberate,
# visible edit, not a silent gap.
NEWCLIENT_INVOKING_FILES = (
    "test_business_newclient_headersafe.py",
    "test_business_newclient_person_manager_refactor.py",
    "test_business_newclient_state_snapshot.py",
    "test_client_caller_migration.py",
)


def _patch_targets_in(node: ast.AST) -> set[str]:
    """All string literals passed as the first argument to any
    patch(...) call anywhere inside `node`."""
    targets = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fname = sub.func.id if isinstance(sub.func, ast.Name) else getattr(sub.func, "attr", None)
            if fname == "patch" and sub.args and isinstance(sub.args[0], ast.Constant):
                targets.add(sub.args[0].value)
    return targets


def _invokes_newclient_confirm(node: ast.AST) -> bool:
    """True iff `node` contains a call to newclient_confirm() — either
    directly by name, as an attribute (th.newclient_confirm), or via
    the handlers["confirm"] indirection used in
    test_business_newclient_state_snapshot.py."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name) and func.id == "newclient_confirm":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "newclient_confirm":
            return True
        if (
            isinstance(func, ast.Subscript)
            and isinstance(func.value, ast.Name) and func.value.id == "handlers"
            and isinstance(func.slice, ast.Constant) and func.slice.value == "confirm"
        ):
            return True
    return False


def _resolve_local_assignment(node: ast.AST, name: str) -> ast.AST | None:
    """One-level local-variable resolution: find `name = <value>` inside
    `node` and return <value>. Handles the
    `identity = {...}; patch(..., return_value=identity)` pattern used
    in test_client_caller_migration.py."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for target in sub.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return sub.value
    return None


def _dict_literal_str_value(d: ast.Dict, key: str):
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and k.value == key and isinstance(v, ast.Constant):
            return v.value
    return None


def _resolve_person_identity_status(node: ast.AST) -> tuple[str | None, bool | None]:
    """Best-effort static determination of (status, same_biz) the
    mocked resolve_person_identity() call returns within `node`, for
    scoping strategy (B)'s requirements. same_biz is only meaningful
    for "single_match" (append_person_biz_id is only reachable when
    same_biz is False). Returns (None, None) if it cannot be
    determined (callers must then fail safe to the full requirement
    set)."""
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Call) and _is_patch_call(sub)):
            continue
        if not (sub.args and isinstance(sub.args[0], ast.Constant)):
            continue
        if sub.args[0].value != "business_core.person_manager.resolve_person_identity":
            continue

        return_value = next((kw.value for kw in sub.keywords if kw.arg == "return_value"), None)
        if return_value is None:
            return (None, None)

        if isinstance(return_value, ast.Name):
            resolved = _resolve_local_assignment(node, return_value.id)
            if resolved is not None:
                return_value = resolved

        # Direct dict literal: {"status": "...", ...}
        if isinstance(return_value, ast.Dict):
            status = _dict_literal_str_value(return_value, "status")
            return (status, None)

        # _identity_result_from_legacy(None) -> not_found;
        # _identity_result_from_legacy({..., "same_biz": X, ...}) -> single_match
        # (both test files' own helper follows this exact contract).
        if isinstance(return_value, ast.Call):
            fname = return_value.func.id if isinstance(return_value.func, ast.Name) else None
            if fname == "_identity_result_from_legacy" and return_value.args:
                arg0 = return_value.args[0]
                if isinstance(arg0, ast.Constant) and arg0.value is None:
                    return ("not_found", None)
                if isinstance(arg0, ast.Dict):
                    same_biz = _dict_literal_str_value(arg0, "same_biz")
                    return ("single_match", same_biz)
        return (None, None)
    return (None, None)


def _ensure_client_role_manual_decision(node: ast.AST) -> bool | None:
    """True iff a mocked ensure_client_role() in `node` returns
    manual_decision_required=True (code returns before touching
    Business-link/Drive in that case). None if not statically
    determinable."""
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Call) and _is_patch_call(sub)):
            continue
        if not (sub.args and isinstance(sub.args[0], ast.Constant)):
            continue
        if sub.args[0].value != "business_core.person_manager.ensure_client_role":
            continue
        return_value = next((kw.value for kw in sub.keywords if kw.arg == "return_value"), None)
        if isinstance(return_value, ast.Dict):
            return bool(_dict_literal_str_value(return_value, "manual_decision_required"))
        return None
    return None


def _create_person_ok(node: ast.AST) -> bool | None:
    """False iff a mocked create_person() in `node` returns ok=False
    (code returns before touching update_person/Drive). None if not
    statically determinable."""
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Call) and _is_patch_call(sub)):
            continue
        if not (sub.args and isinstance(sub.args[0], ast.Constant)):
            continue
        if sub.args[0].value != "business_core.person_manager.create_person":
            continue
        return_value = next((kw.value for kw in sub.keywords if kw.arg == "return_value"), None)
        if isinstance(return_value, ast.Dict):
            ok = _dict_literal_str_value(return_value, "ok")
            return ok
        return None
    return None


# Explicit, named exemptions for invocation sites that return before
# ever reaching resolve_person_identity() at all (cancel / missing-
# confirmed-snapshot early-return paths) — verified by direct reading,
# not inferred. Adding an entry here must be a deliberate, reviewed
# choice, not a way to silence a real gap.
_EARLY_RETURN_BEFORE_IDENTITY_RESOLUTION = frozenset({
    "test_business_newclient_state_snapshot.py::test_cancel_clears_snapshot",
    "test_business_newclient_state_snapshot.py::test_confirm_without_snapshot_does_not_write",
})


def _is_patch_call(node: ast.Call) -> bool:
    fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
    return fname == "patch"


def _test_methods(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            yield node


def _all_invoking_callables(tree: ast.AST):
    """Every FunctionDef/AsyncFunctionDef anywhere in the module that
    invokes newclient_confirm(), named "test_*" or not (covers helper
    methods like _run_newclient_confirm()/_confirm_with_mocks())."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _invokes_newclient_confirm(node):
            yield node


class TestNewClientTestsFullyMockRequiredCallPoints(unittest.TestCase):
    """Regression guard for the PRS-003 production-write incident."""

    def test_every_newclient_invocation_site_is_isolated_from_production(self):
        violations: dict[str, list[str]] = {}

        for filename in NEWCLIENT_INVOKING_FILES:
            path = WORKSPACE / filename
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, str(path))

            for func in _all_invoking_callables(tree):
                key = f"{filename}::{func.name}"
                patched = _patch_targets_in(func)

                if SHEET_LEVEL_TARGET in patched:
                    continue  # strategy (A) — fully isolated regardless of status

                if key in _EARLY_RETURN_BEFORE_IDENTITY_RESOLUTION:
                    continue  # verified: returns before reaching resolve_person_identity() at all

                if "business_core.person_manager.resolve_person_identity" not in patched:
                    violations[key] = [
                        "business_core.person_manager.resolve_person_identity (root cause of PRS-003: "
                        "identity resolution ran for real)"
                    ]
                    continue

                status, same_biz = _resolve_person_identity_status(func)
                required = set(_STATUS_REQUIREMENTS.get(status, REQUIRED_MOCK_TARGETS))

                if status == "single_match" and same_biz is True:
                    # SAME_BIZ: append_person_biz_id is only reachable when NOT same_biz.
                    required.discard("business_core.person_manager.append_person_biz_id")

                if status == "not_found" and _create_person_ok(func) is False:
                    # create_person() itself failed -> update_person/Drive never reached.
                    required &= {
                        "business_core.person_manager.resolve_person_identity",
                        "business_core.person_manager.create_person",
                    }

                if status == "single_match" and _ensure_client_role_manual_decision(func) is True:
                    # manual_decision_required=True -> returns before Business-link/Drive.
                    required &= {
                        "business_core.person_manager.resolve_person_identity",
                        "business_core.person_manager.ensure_client_role",
                    }

                missing = required - patched
                if missing:
                    violations[key] = sorted(missing)

        self.assertEqual(
            violations, {},
            f"Invocation site(s) of newclient_confirm() not fully isolated from "
            f"production (see module docstring for strategies A/B): {violations}",
        )

    def test_at_least_one_invocation_site_exists_per_file(self):
        """Sanity check on the guard itself: if a listed file no longer
        contains any newclient_confirm()-invoking callable, the guard
        above would vacuously pass without checking anything."""
        for filename in NEWCLIENT_INVOKING_FILES:
            path = WORKSPACE / filename
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, str(path))
            invoking = [f.name for f in _all_invoking_callables(tree)]
            self.assertTrue(invoking, f"{filename} is listed as newclient-invoking but no callable calls it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
