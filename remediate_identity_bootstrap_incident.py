"""
Phase 17B-IR3A — dedicated, one-purpose CLI for the Phase 17B-IR1
incident (an unmocked test run wrote a placeholder OWNER bootstrap to
production: EMP-001/TGID-001/ARA-001/ASA-001, Telegram User ID "999").

This script accepts NO target arguments — every ID/actor/reason is
fixed inside business_builder.remediate_phase17b_identity_incident().
There is no Telegram User ID, Employee ID, Role Assignment ID, actor,
or reason CLI argument, by design — this is a one-incident remediation
tool, not a general-purpose identity-admin script.

Never run automatically during startup, migration, or deploy.

Usage:
    python remediate_identity_bootstrap_incident.py
        # dry-run: read-only precondition check + planned remaining
        # steps, zero writes

    python remediate_identity_bootstrap_incident.py --live YES
        # execute exactly the remaining remediation steps (revoke
        # ARA-001 -> revoke TGID-001 -> disable EMP-001, in that
        # order; ASA-001 is verified already-revoked, never
        # re-revoked)
"""

from __future__ import annotations

import sys


def _print_result(result: dict) -> None:
    print(f"ok: {result['ok']}")
    print(f"code: {result['code']}")
    print(f"changed: {result['changed']}")
    print(f"retry_safe: {result['retry_safe']}")
    print(f"dry_run: {result['dry_run']}")
    print(f"completed_steps: {result['completed_steps']}")
    print(f"pending_steps: {result['pending_steps']}")
    if result["failed_step"]:
        print(f"failed_step: {result['failed_step']}")
    if result["result_by_step"]:
        print(f"result_by_step: {result['result_by_step']}")
    if result["verification_errors"]:
        print(f"verification_errors: {result['verification_errors']}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", default="", help="Pass YES to execute the remaining remediation steps (default: dry-run)")
    args = parser.parse_args()

    live = args.live == "YES"

    from business_core.business_builder import remediate_phase17b_identity_incident

    print("=" * 60)
    print("Phase 17B-IR1 incident remediation — fixed target: "
          "ARA-001 / TGID-001 / EMP-001 (ASA-001 already revoked)")
    print("=" * 60)

    preview = remediate_phase17b_identity_incident(dry_run=True)
    print("\n--- Precondition check + preview ---")
    _print_result(preview)

    if not preview["ok"]:
        print("\n❌ Preconditions not met — remediation cancelled. No writes attempted.")
        return 1

    if not preview["pending_steps"]:
        print("\nAlready fully remediated — nothing to do.")
        return 0

    if not live:
        print("\n[DRY-RUN] Изменения НЕ применены. Запустите с --live YES для выполнения.")
        return 0

    confirm = input("\nВведите YES для выполнения оставшихся шагов remediation: ").strip()
    if confirm != "YES":
        print("Отменено.")
        return 0

    result = remediate_phase17b_identity_incident(dry_run=False)
    print("\n--- Live remediation result ---")
    _print_result(result)

    if result["ok"]:
        print("\n✅ Remediation complete.")
        return 0

    print("\n❌ Remediation stopped — see failed_step/verification_errors above. No automatic retry, no rollback.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
