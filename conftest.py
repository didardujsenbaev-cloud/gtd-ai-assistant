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
mode: for every test file that exercises the Client Domain (/newclient,
/clients, /bc, /newobject's Client validation, Person Manager, Drive
provisioning), socket.socket.connect()/connect_ex() are blocked for the
whole test file, regardless of whether any individual test's mocks are
correct. A test that is properly mocked never touches a real socket and
is unaffected; a test whose mock target has drifted now fails loudly
and immediately (AssertionError) instead of silently writing to
production.

Scoped to the known Client Domain test files by exact basename — NOT a
blanket rule for the whole test suite, since other domains' tests are
out of scope for this incident and this guard.
"""

from __future__ import annotations

import socket

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


def _blocked_connect(*_args, **_kwargs):
    raise AssertionError(
        "Client Domain test attempted a live socket connection — a mock "
        "target has likely drifted from the real call site (see "
        "conftest.py's module docstring for the PRS-003 incident this "
        "guard exists to prevent). No test in this file may reach "
        "production Google Sheets/Drive."
    )


@pytest.fixture(autouse=True)
def _block_live_sockets_for_client_domain_tests(request):
    test_file_name = request.node.fspath.basename
    if test_file_name not in _CLIENT_DOMAIN_TEST_FILES:
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
