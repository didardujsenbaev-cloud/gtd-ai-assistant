"""
Phase 12A: business_core.version_info / /version command — mock tests.

get_version_info() must never touch Google Sheets/Drive — it only reads
the bundled VERSION text file (git-tracked; *.json is repo-gitignored)
and Railway environment variables. version_cmd() is a thin read-only
Telegram wrapper around it, following the same pattern as report_cmd().
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, AsyncMock, patch


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core import version_info
    from business_core.telegram_handlers import version_cmd
    return version_info, version_cmd


class TestReadVersionFile(unittest.TestCase):
    def test_parses_key_value_lines(self):
        version_info, _ = _fresh_import()
        with tempfile.NamedTemporaryFile("w", suffix=".tmp", delete=False) as f:
            f.write("commit_sha=abc123\ngenerated_at=2026-01-01T00:00:00Z\n")
            path = f.name
        try:
            data = version_info._read_version_file(path)
            self.assertEqual(data["commit_sha"], "abc123")
            self.assertEqual(data["generated_at"], "2026-01-01T00:00:00Z")
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty_dict(self):
        version_info, _ = _fresh_import()
        data = version_info._read_version_file("/nonexistent/path/VERSION")
        self.assertEqual(data, {})

    def test_ignores_blank_and_malformed_lines(self):
        version_info, _ = _fresh_import()
        with tempfile.NamedTemporaryFile("w", suffix=".tmp", delete=False) as f:
            f.write("\ncommit_sha=xyz\n\nmalformed line without equals\n")
            path = f.name
        try:
            data = version_info._read_version_file(path)
            self.assertEqual(data, {"commit_sha": "xyz"})
        finally:
            os.unlink(path)


def _clean_commit_env():
    """Strip every commit-related env var so tests control the priority
    chain deterministically regardless of the actual shell environment."""
    env = os.environ.copy()
    for k in ("APP_COMMIT_SHA", "RAILWAY_GIT_COMMIT_SHA", "APP_BUILD_TIMESTAMP"):
        env.pop(k, None)
    return env


class TestGetVersionInfo(unittest.TestCase):
    def test_returns_all_expected_keys(self):
        version_info, _ = _fresh_import()
        info = version_info.get_version_info()
        self.assertEqual(
            set(info.keys()),
            {"commit_sha", "source", "build_timestamp", "environment",
             "deployment_id", "warning"},
        )

    def test_app_commit_sha_has_highest_priority(self):
        """1. APP_COMMIT_SHA имеет высший приоритет — даже если
        RAILWAY_GIT_COMMIT_SHA и VERSION тоже доступны."""
        version_info, _ = _fresh_import()
        env = _clean_commit_env()
        env["APP_COMMIT_SHA"] = "runtime1234567890"
        env["RAILWAY_GIT_COMMIT_SHA"] = "railway0987654321"
        with patch.dict(os.environ, env, clear=True):
            info = version_info.get_version_info()
        self.assertEqual(info["commit_sha"], "runtime1234567890")
        self.assertEqual(info["source"], "runtime_env")
        self.assertEqual(info["warning"], "")

    def test_railway_sha_used_when_app_commit_sha_absent(self):
        """2. Railway SHA используется при отсутствии APP_COMMIT_SHA."""
        version_info, _ = _fresh_import()
        env = _clean_commit_env()
        env["RAILWAY_GIT_COMMIT_SHA"] = "railway0987654321"
        with patch.dict(os.environ, env, clear=True):
            info = version_info.get_version_info()
        self.assertEqual(info["commit_sha"], "railway0987654321")
        self.assertEqual(info["source"], "railway_env")
        self.assertEqual(info["warning"], "")

    def test_version_file_is_static_fallback(self):
        """3. VERSION определяется как static_fallback, с warning."""
        version_info, _ = _fresh_import()
        with tempfile.NamedTemporaryFile("w", suffix=".tmp", delete=False) as f:
            f.write("commit_sha=fileFallbackSha\ngenerated_at=2026-01-01T00:00:00Z\n")
            path = f.name
        try:
            env = _clean_commit_env()
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(version_info, "_VERSION_FILE", path):
                info = version_info.get_version_info()
        finally:
            os.unlink(path)
        self.assertEqual(info["commit_sha"], "fileFallbackSha")
        self.assertEqual(info["source"], "static_fallback")
        self.assertEqual(info["build_timestamp"], "2026-01-01T00:00:00Z")
        self.assertIn("runtime commit not provided", info["warning"])

    def test_unknown_when_nothing_available(self):
        """4. unknown корректно обрабатывается — вместе с warning."""
        version_info, _ = _fresh_import()
        env = _clean_commit_env()
        with patch.dict(os.environ, env, clear=True), \
             patch.object(version_info, "_VERSION_FILE", "/nonexistent/VERSION"):
            info = version_info.get_version_info()
        self.assertEqual(info["commit_sha"], "unknown")
        self.assertEqual(info["source"], "unknown")
        self.assertEqual(info["build_timestamp"], "unknown")
        self.assertIn("runtime commit not provided", info["warning"])

    def test_warning_absent_for_runtime_and_railway_sources(self):
        """5. Warning появляется ТОЛЬКО для fallback/unknown, не для
        runtime_env/railway_env."""
        version_info, _ = _fresh_import()
        for var, value in [("APP_COMMIT_SHA", "abc"), ("RAILWAY_GIT_COMMIT_SHA", "def")]:
            env = _clean_commit_env()
            env[var] = value
            with patch.dict(os.environ, env, clear=True):
                info = version_info.get_version_info()
            self.assertEqual(info["warning"], "", f"unexpected warning for {var}")

    def test_build_timestamp_prefers_app_env_var(self):
        version_info, _ = _fresh_import()
        env = _clean_commit_env()
        env["APP_BUILD_TIMESTAMP"] = "2026-07-18T20:00:00Z"
        with patch.dict(os.environ, env, clear=True):
            info = version_info.get_version_info()
        self.assertEqual(info["build_timestamp"], "2026-07-18T20:00:00Z")

    def test_reads_real_commit_sha_or_falls_back_cleanly(self):
        """The actual VERSION file checked into this repo must parse
        without raising, whatever the current environment provides."""
        version_info, _ = _fresh_import()
        info = version_info.get_version_info()
        self.assertRegex(info["commit_sha"], r"^[0-9a-fA-F]{6,40}$|^unknown$")
        self.assertIn(info["source"], ("runtime_env", "railway_env", "static_fallback", "unknown"))

    def test_environment_from_railway_env_var(self):
        version_info, _ = _fresh_import()
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}):
            info = version_info.get_version_info()
        self.assertEqual(info["environment"], "production")

    def test_environment_unknown_when_env_var_absent(self):
        version_info, _ = _fresh_import()
        env = os.environ.copy()
        env.pop("RAILWAY_ENVIRONMENT_NAME", None)
        with patch.dict(os.environ, env, clear=True):
            info = version_info.get_version_info()
        self.assertEqual(info["environment"], "unknown")

    def test_deployment_id_from_railway_env_var(self):
        version_info, _ = _fresh_import()
        with patch.dict(os.environ, {"RAILWAY_DEPLOYMENT_ID": "dep-123"}):
            info = version_info.get_version_info()
        self.assertEqual(info["deployment_id"], "dep-123")

    def test_no_live_api_calls(self):
        version_info, _ = _fresh_import()
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            version_info.get_version_info()
        mock_get_sheet.assert_not_called()


def _make_update_context():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    return update, context


class TestVersionCmd(unittest.TestCase):
    def test_replies_with_all_fields_no_warning_for_runtime_source(self):
        _, version_cmd = _fresh_import()
        update, context = _make_update_context()

        fake_info = {
            "commit_sha": "deadbeef" * 5,
            "source": "runtime_env",
            "build_timestamp": "2026-07-18T16:26:05Z",
            "environment": "production",
            "deployment_id": "dep-999",
            "warning": "",
        }
        with patch("business_core.version_info.get_version_info", return_value=fake_info):
            asyncio.run(version_cmd(update, context))

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn(fake_info["commit_sha"], msg)
        self.assertIn(fake_info["source"], msg)
        self.assertIn(fake_info["build_timestamp"], msg)
        self.assertIn(fake_info["environment"], msg)
        self.assertIn(fake_info["deployment_id"], msg)
        self.assertNotIn("Warning", msg)

    def test_replies_with_warning_for_static_fallback_source(self):
        _, version_cmd = _fresh_import()
        update, context = _make_update_context()

        fake_info = {
            "commit_sha": "7df6032b72df33f5be54714468167ea57ef75037",
            "source": "static_fallback",
            "build_timestamp": "2026-07-18T16:26:05Z",
            "environment": "production",
            "deployment_id": "dep-999",
            "warning": "runtime commit not provided",
        }
        with patch("business_core.version_info.get_version_info", return_value=fake_info):
            asyncio.run(version_cmd(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("static_fallback", msg)
        self.assertIn("Warning", msg)
        self.assertIn("runtime commit not provided", msg)

    def test_exception_does_not_propagate(self):
        _, version_cmd = _fresh_import()
        update, context = _make_update_context()

        with patch("business_core.version_info.get_version_info",
                   side_effect=RuntimeError("boom")):
            asyncio.run(version_cmd(update, context))

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)

    def test_no_sheets_or_drive_calls(self):
        _, version_cmd = _fresh_import()
        update, context = _make_update_context()

        with patch("business_core.sheets.get_business_sheet") as mock_sheet, \
             patch("business_core.sheets.read_business_sheet") as mock_read:
            asyncio.run(version_cmd(update, context))

        mock_sheet.assert_not_called()
        mock_read.assert_not_called()


class TestVersionCmdRegistered(unittest.TestCase):
    def test_version_command_registered_exactly_once(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import inspect
        from business_core.telegram_handlers import register_business_handlers
        src = inspect.getsource(register_business_handlers)
        self.assertEqual(src.count('CommandHandler("version"'), 1)


class TestImportSafety(unittest.TestCase):
    def test_import_does_not_touch_sheets(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.version_info  # noqa: F401
            import business_core.telegram_handlers  # noqa: F401
        mock_get_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
