"""
Phase 31D incident response: a real Person row (PRS-003) was created in
production PEOPLE_REGISTRY by a Client Domain test whose mocks targeted
a stale call site (business_builder.find_existing_person/
provision_client_drive/update_person_drive_info) instead of the ones
newclient_confirm() actually calls after migration (person_manager.
resolve_person_identity/create_person/update_person, business_builder.
provision_client_drive_safe, person_manager.update_person_drive_info).
Because the mocks didn't match the real call points, the test silently
fell through to real business logic, which made real network calls
against production Google Sheets/Drive.

This is a hard, mock-independent safety net for exactly that failure
mode: for every listed test file, socket.socket.connect()/connect_ex()
are blocked for the whole file, regardless of whether any individual
test's mocks are correct. A test that is properly mocked never touches
a real socket and is unaffected; a test whose mock target has drifted
now fails loudly and immediately (AssertionError) instead of silently
writing to production.

Scoped to known test files by exact basename — NOT a blanket rule for
the whole test suite, since files outside these domains are out of
scope for the incidents/audits below.

Phase 33C (ADR-016, Roadmap Cross-Domain Validation): extends this same
guard to every Roadmap/Stage/Template/Milestone test file, per the
Phase 33B ADR's explicit requirement that the PRS-003 incident be
treated as a permanent, binding precedent for test isolation in any
future Roadmap Domain phase — not a one-off fix scoped only to the
Client Domain. Also includes test_service_ownership_migration.py, where
Phase 32A (Service Domain re-audit) found a masked live-network call
(0.9s under socket-block vs ~20s unblocked) that predates this session
and was never fixed.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

_CLIENT_DOMAIN_TEST_FILES = frozenset({
    "test_business_newclient_headersafe.py",
    "test_business_newclient_person_manager_refactor.py",
    "test_business_newclient_state_snapshot.py",
    "test_business_client_dedup.py",
    "test_business_editclient.py",
    "test_business_builder_client_drive.py",
    "test_business_person_manager.py",
    "test_business_person_identity_resolver.py",
    "test_client_architecture_guards.py",
    "test_client_caller_migration.py",
    "test_client_newclient_mock_completeness.py",
})

# Phase 33C (ADR-016 §16/§20): every Roadmap/Stage/Template/Milestone
# test file identified in the Phase 33A audit, plus the Phase 33C
# foundation's own new test file(s) and the seed/architecture-guard
# files that directly invoke business_builder.create_roadmap_for_object().
_ROADMAP_DOMAIN_TEST_FILES = frozenset({
    "test_roadmap_architecture_guards.py",
    "test_roadmap_manager_canonical_api.py",
    "test_roadmap_convergent_retry.py",
    "test_roadmap_completion.py",
    "test_roadmap_progress.py",
    "test_roadmap_template_id_persistence.py",
    "test_startroadmap_template_selection.py",
    "test_business_roadmap_templates.py",
    "test_business_stage_entity_relations.py",
    "test_business_stage_id_generation.py",
    "test_business_stage_management.py",
    "test_milestones_command.py",
    "test_updatestage.py",
    "test_updatestage_completion.py",
    "test_updatestage_progress.py",
    "test_updatestage_reliability.py",
    "test_business_newroadmap_deprecation.py",
    "test_roadmaps_header_migration.py",
    "test_roadmap_stages_header_migration.py",
    "test_business_object_roadmaps.py",
    "test_seed_izhs_almaty_standard_reconstruction.py",
    "test_seed_izhs_almaty_legalization.py",
    "test_object_architecture_guards.py",
    "test_service_architecture_guards.py",
    "test_roadmap_cross_domain_validation.py",
})

# Phase 32A (Service Domain re-audit) found a masked live-network call
# here — pre-existing, never fixed. Included per Phase 33C's explicit
# requirement (ADR-016 §16).
_OTHER_HARDENED_TEST_FILES = frozenset({
    "test_service_ownership_migration.py",
})

_HARD_SOCKET_BLOCK_TEST_FILES = _CLIENT_DOMAIN_TEST_FILES | _ROADMAP_DOMAIN_TEST_FILES | _OTHER_HARDENED_TEST_FILES


def _blocked_connect(*_args, **_kwargs):
    raise AssertionError(
        "Test attempted a live socket connection — a mock target has "
        "likely drifted from the real call site (see conftest.py's "
        "module docstring for the PRS-003 incident and the Phase 32A/33A "
        "findings this guard exists to prevent). No test in this file "
        "may reach production Google Sheets/Drive."
    )


@pytest.fixture(autouse=True)
def _block_live_sockets_for_hardened_tests(request):
    test_file_name = request.node.fspath.basename
    if test_file_name not in _HARD_SOCKET_BLOCK_TEST_FILES:
        yield
        return

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    socket.socket.connect = _blocked_connect
    socket.socket.connect_ex = _blocked_connect
    try:
        yield
    finally:
        socket.socket.connect = real_connect
        socket.socket.connect_ex = real_connect_ex


def _default_find_row_by_id(sheet_key, row_id):
    """Safe default: 'found' for any sheet_key/row_id. Only reached in
    the Roadmap test file set (see below) where the sole real caller is
    business_builder.create_roadmap_for_object()'s new Business-existence
    check (ADR-016 §2) — Object/Service/Person lookups in these tests
    are mocked at their own manager-level functions, never via this raw
    primitive, so a single generic 'found' default is safe here."""
    return ("2", {"ID": row_id})


@pytest.fixture(autouse=True)
def _default_roadmap_cross_domain_validation_mocks(request):
    """
    Phase 33C (ADR-016): business_builder.create_roadmap_for_object() now
    validates Business existence and Client existence/archive/role/
    Business-link before Object/Service/Template/duplicate logic runs.
    Every pre-existing Roadmap test in _ROADMAP_DOMAIN_TEST_FILES was
    written before these checks existed, so none of them mock these new
    call points — without this fixture, every one of them would either
    fail (if a test's own inner `with patch(...)` didn't happen to also
    stub these) or, worse, silently reach a real network call (exactly
    the PRS-003 failure mode this session's conftest.py exists to catch).

    This fixture provides an "everything passes" default for the new
    checks ONLY — Business exists, Client exists/active/has Client role/
    linked to any Business — so every pre-existing test continues to
    exercise the Object/Service/Template/duplicate-Roadmap logic it was
    actually written to test. A test that specifically wants to exercise
    a NEW rejection path (e.g. CLIENT_ARCHIVED) adds its own nested
    `with patch(...)` for that one function inside the test body, which
    correctly overrides this fixture's default for that call only
    (standard unittest.mock.patch stacking — the innermost active patch
    wins), then reverts to this fixture's default once that nested
    `with` block exits.
    """
    test_file_name = request.node.fspath.basename
    if test_file_name not in _ROADMAP_DOMAIN_TEST_FILES:
        yield
        return

    default_person = {
        "person_id": "PRS-DEFAULT", "status": "active",
        "person_type": "клиент", "biz_ids": [], "primary_biz_id": "",
    }

    with patch("business_core.sheets.find_row_by_id", side_effect=_default_find_row_by_id), \
         patch("business_core.person_manager.find_person_by_id", return_value=default_person), \
         patch("business_core.person_manager.is_person_archived", return_value=False), \
         patch("business_core.person_manager.is_client_person", return_value=True), \
         patch("business_core.person_manager.has_person_business_link", return_value=True):
        yield
