"""
Phase 12A: runtime build/version provenance.

Motivation: Phase 11H/11I discovered that `railway redeploy` can silently
keep serving an old build with no way to tell from the running process
alone. There was no runtime marker to distinguish "Online" from
"actually running the commit we think we pushed" — verifying that
required manually SSH-ing into the container and hashing files.

This module exposes a read-only version snapshot so that mismatch can
be caught immediately (e.g. via /version) without SSH access.

Commit SHA resolution priority (Phase 12A correction):
  1. APP_COMMIT_SHA        — runtime env var, set explicitly at deploy
                              time to the exact commit being deployed
                              (source: "runtime_env").
  2. RAILWAY_GIT_COMMIT_SHA — set automatically by Railway for
                              git-triggered builds, if present
                              (source: "railway_env").
  3. VERSION file           — git-tracked static fallback (source:
                              "static_fallback"). Because a commit
                              cannot embed its own SHA, VERSION always
                              reflects the PARENT of the commit that
                              includes it — it is a known-stale
                              approximation, never a guarantee.
  4. "unknown"              — none of the above available.

Only the first two sources are treated as an authoritative statement
of "this is the commit currently running". Source 3/4 are surfaced
with an explicit warning so nothing consuming /version can mistake a
static fallback for a verified runtime commit.

Build timestamp follows the same shape: APP_BUILD_TIMESTAMP (runtime
env, set at deploy time) → VERSION file's generated_at → "unknown".
Railway does not expose a deployment-build-time env var to the running
container, so there is no separate "railway" tier for the timestamp.
"""

from __future__ import annotations

import os

_VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION")


def _read_version_file(path: str | None = None) -> dict:
    if path is None:
        path = _VERSION_FILE
    data: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                data[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return data


def get_version_info() -> dict:
    """
    Собрать доступную информацию о версии/деплое, с явным источником и
    предупреждением, если commit SHA не подтверждён рантайм-окружением.

    Returns:
        {
            "commit_sha":      str,
            "source":          "runtime_env" | "railway_env" | "static_fallback" | "unknown",
            "build_timestamp": str,
            "environment":     str,  # RAILWAY_ENVIRONMENT_NAME или "unknown"
            "deployment_id":   str,  # RAILWAY_DEPLOYMENT_ID или "unknown"
            "warning":         str,  # непусто только для static_fallback/unknown
        }
    """
    file_data: dict | None = None

    def _file_data() -> dict:
        nonlocal file_data
        if file_data is None:
            file_data = _read_version_file()
        return file_data

    commit_sha = os.environ.get("APP_COMMIT_SHA", "").strip()
    if commit_sha:
        source = "runtime_env"
    else:
        commit_sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "").strip()
        if commit_sha:
            source = "railway_env"
        else:
            commit_sha = _file_data().get("commit_sha", "").strip()
            if commit_sha:
                source = "static_fallback"
            else:
                commit_sha = "unknown"
                source = "unknown"

    build_timestamp = os.environ.get("APP_BUILD_TIMESTAMP", "").strip()
    if not build_timestamp:
        build_timestamp = _file_data().get("generated_at", "").strip()
    if not build_timestamp:
        build_timestamp = "unknown"

    warning = "runtime commit not provided" if source in ("static_fallback", "unknown") else ""

    return {
        "commit_sha": commit_sha,
        "source": source,
        "build_timestamp": build_timestamp,
        "environment": os.environ.get("RAILWAY_ENVIRONMENT_NAME", "unknown"),
        "deployment_id": os.environ.get("RAILWAY_DEPLOYMENT_ID", "unknown"),
        "warning": warning,
    }
