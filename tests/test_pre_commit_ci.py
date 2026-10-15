import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).parents[1] / "pre-commit.py"
SPEC = importlib.util.spec_from_file_location("quasarr_pre_commit", MODULE_PATH)
pre_commit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pre_commit)


class PreCommitCITests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "TARGET_REF": "dev",
            "PR_NUMBER": "123",
            "WORKFLOW_NAME": "Pull Requests",
        }

    def run_main(self, args, task_deps=False, task_format=False, version=False):
        calls = []

        def fake_run(cmd, check=True, **kwargs):
            calls.append((cmd, check))
            return subprocess.CompletedProcess(cmd, 0)

        with (
            mock.patch.object(sys, "argv", [str(MODULE_PATH), *args]),
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(pre_commit, "run", side_effect=fake_run),
            mock.patch.object(pre_commit, "task_upgrade_deps", return_value=task_deps),
            mock.patch.object(pre_commit, "task_format", return_value=task_format),
            mock.patch.object(pre_commit, "task_tests"),
            mock.patch.object(
                pre_commit, "task_version_bump", return_value=(version, "4.0.0")
            ),
            mock.patch.object(Path, "write_text"),
        ):
            try:
                pre_commit.main()
            except SystemExit as exc:
                return exc.code, calls
        return 0, calls

    def test_changed_deps_pushes_and_dispatches_one_read_only_followup(self):
        code, calls = self.run_main(["--ci"], task_deps=True)

        self.assertEqual(code, 0)
        commands = [cmd for cmd, _ in calls]
        dispatches = [cmd for cmd in commands if cmd[:3] == ["gh", "workflow", "run"]]
        self.assertEqual(
            dispatches,
            [
                [
                    "gh",
                    "workflow",
                    "run",
                    "Pull Requests",
                    "--ref",
                    "dev",
                    "--field",
                    "auto_fix_followup=true",
                ]
            ],
        )
        self.assertIn(["git", "push", "origin", "HEAD:dev"], commands)

    def test_failed_followup_dispatch_fails_ci(self):
        calls = []

        def fake_run(cmd, check=True, **kwargs):
            calls.append(cmd)
            status = 1 if cmd[:3] == ["gh", "workflow", "run"] else 0
            return subprocess.CompletedProcess(cmd, status)

        with (
            mock.patch.object(sys, "argv", [str(MODULE_PATH), "--ci"]),
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(pre_commit, "run", side_effect=fake_run),
            mock.patch.object(pre_commit, "task_upgrade_deps", return_value=True),
            mock.patch.object(pre_commit, "task_format", return_value=False),
            mock.patch.object(pre_commit, "task_tests"),
            mock.patch.object(
                pre_commit, "task_version_bump", return_value=(False, "")
            ),
            mock.patch.object(Path, "write_text"),
        ):
            with self.assertRaises(SystemExit) as exit_info:
                pre_commit.main()

        self.assertEqual(exit_info.exception.code, 1)
        self.assertEqual(sum(cmd[:3] == ["gh", "workflow", "run"] for cmd in calls), 1)

    def test_clean_run_does_not_dispatch(self):
        code, calls = self.run_main(["--ci"])

        self.assertEqual(code, 0)
        self.assertFalse(any(cmd[:3] == ["gh", "workflow", "run"] for cmd, _ in calls))

    def test_check_run_uses_locked_checks_without_upgrades(self):
        calls = []

        def fake_run(cmd, check=True, **kwargs):
            calls.append((cmd, check))
            return subprocess.CompletedProcess(cmd, 0)

        with (
            mock.patch.object(sys, "argv", [str(MODULE_PATH), "--check"]),
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(pre_commit, "run", side_effect=fake_run),
            mock.patch.object(pre_commit, "task_upgrade_deps") as upgrade,
            mock.patch.object(pre_commit, "task_format") as formatting,
            mock.patch.object(pre_commit, "task_tests") as tests,
            mock.patch.object(pre_commit, "task_version_bump") as version,
            mock.patch.object(Path, "write_text"),
        ):
            with self.assertRaises(SystemExit) as exit_info:
                pre_commit.main()

        code = exit_info.exception.code

        self.assertEqual(code, 0)
        commands = [cmd for cmd, _ in calls]
        self.assertIn(["uv", "lock", "--check"], commands)
        self.assertTrue(all(cmd[:3] != ["uv", "add", "--upgrade"] for cmd in commands))
        self.assertFalse(any(cmd[-1:] == ["--upgrade"] for cmd in commands))
        self.assertTrue(
            all("--locked" in cmd for cmd in commands if cmd[:2] == ["uv", "run"])
        )
        upgrade.assert_not_called()
        formatting.assert_not_called()
        tests.assert_not_called()
        version.assert_not_called()
        self.assertFalse(any(cmd[:2] == ["git", "commit"] for cmd in commands))
        self.assertFalse(any(cmd[:2] == ["git", "push"] for cmd in commands))
        self.assertFalse(any(cmd[:3] == ["gh", "workflow", "run"] for cmd in commands))

    def test_failed_check_exits_without_mutation_or_dispatch(self):
        calls = []

        def fake_run(cmd, check=True, **kwargs):
            calls.append(cmd)
            status = 1 if cmd == ["uv", "lock", "--check"] else 0
            return subprocess.CompletedProcess(cmd, status)

        with (
            mock.patch.object(sys, "argv", [str(MODULE_PATH), "--check"]),
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(pre_commit, "run", side_effect=fake_run),
            mock.patch.object(pre_commit, "task_upgrade_deps") as upgrade,
            mock.patch.object(pre_commit, "task_format") as formatting,
            mock.patch.object(pre_commit, "task_tests") as tests,
            mock.patch.object(pre_commit, "task_version_bump") as version,
            mock.patch.object(Path, "write_text"),
        ):
            with self.assertRaises(SystemExit) as exit_info:
                pre_commit.main()

        self.assertEqual(exit_info.exception.code, 1)
        upgrade.assert_not_called()
        formatting.assert_not_called()
        tests.assert_not_called()
        version.assert_not_called()
        self.assertFalse(any(cmd[:2] == ["git", "commit"] for cmd in calls))
        self.assertFalse(any(cmd[:2] == ["git", "push"] for cmd in calls))
        self.assertFalse(any(cmd[:3] == ["gh", "workflow", "run"] for cmd in calls))

    def test_upgrade_runs_before_format_and_tests(self):
        order = []
        with (
            mock.patch.object(sys, "argv", [str(MODULE_PATH)]),
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(
                pre_commit,
                "task_upgrade_deps",
                side_effect=lambda: order.append("deps") or False,
            ),
            mock.patch.object(
                pre_commit,
                "task_format",
                side_effect=lambda: order.append("format") or False,
            ),
            mock.patch.object(
                pre_commit, "task_tests", side_effect=lambda: order.append("tests")
            ),
            mock.patch.object(
                pre_commit, "task_version_bump", return_value=(False, "")
            ),
        ):
            pre_commit.main()

        self.assertEqual(order, ["deps", "format", "tests"])

    def test_dependency_upgrade_updates_project_and_groups_then_lock(self):
        calls = []

        def fake_run(cmd, check=True, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        project = {
            "project": {"dependencies": ["alpha>=1.0"]},
            "dependency-groups": {
                "dev": ["beta>=2.0"],
                "build": ["gamma>=3.0"],
            },
        }
        with (
            mock.patch.object(pre_commit, "run", side_effect=fake_run),
            mock.patch.object(pre_commit, "git_status_has_changes", return_value=True),
            mock.patch.object(pre_commit.tomllib, "load", return_value=project),
            mock.patch("builtins.open", mock.mock_open()),
        ):
            self.assertTrue(pre_commit.task_upgrade_deps())

        self.assertEqual(
            calls,
            [
                ["uv", "add", "--upgrade", "alpha"],
                ["uv", "add", "--group", "dev", "--upgrade", "beta"],
                ["uv", "add", "--group", "build", "--upgrade", "gamma"],
                ["uv", "lock", "--upgrade"],
                ["git", "add", "."],
            ],
        )


if __name__ == "__main__":
    unittest.main()
