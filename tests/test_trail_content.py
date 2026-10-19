import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_trail


class TrailContentTests(unittest.TestCase):
    def write(self, root: Path, name: str, content: str) -> None:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def run_check(self, content: str, name: str = ".trail/learnings/example.md"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "quasarr/__init__.py", "")
            self.write(root, name, content)
            return check_trail.check(root)

    def test_accepts_repository_relative_learning(self):
        diagnostics = self.run_check(
            "---\n"
            "title: Keep state local\n"
            "date: 2026-10-19\n"
            "author: Quasarr\n"
            "touches:\n"
            "  - quasarr/__init__.py\n"
            "---\n"
            "Decision: Keep state behind one module.\n"
        )
        self.assertEqual(diagnostics, [])

    def test_rejects_private_values_without_echoing_them(self):
        secret = "token_value_123"
        diagnostics = self.run_check(
            f"---\nauthor: Someone\ntouches:\n  - missing.py\n---\n"
            f"Contact test.user@example.invalid or use https://private.invalid/x.\n"
            f"token: {secret}\n/workspace/private/file\n"
        )
        self.assertGreaterEqual(len(diagnostics), 5)
        rendered = "\n".join(str(item) for item in diagnostics)
        self.assertNotIn(secret, rendered)
        self.assertTrue(
            all(item.path == ".trail/learnings/example.md" for item in diagnostics)
        )

    def test_accepts_existing_filename_but_rejects_domain_shaped_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "quasarr/__init__.py", "")
            self.write(
                root,
                ".trail/learnings/example.md",
                "---\ntitle: Example\ndate: 2026-10-19\nauthor: Quasarr\ntouches:\n  - quasarr/__init__.py\n---\nSee quasarr/__init__.py.\n",
            )
            self.assertEqual(check_trail.check(root), [])
            self.write(
                root,
                ".trail/learnings/example.md",
                "---\ntitle: Example\ndate: 2026-10-19\nauthor: Quasarr\ntouches:\n  - quasarr/__init__.py\n---\nSee private.py.\n",
            )
            self.assertTrue(
                any("domain-like" in item.reason for item in check_trail.check(root))
            )

    def test_rejects_tracked_private_cache_and_escape_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, ".trail/local/user.md", "private")
            self.write(root, ".trail/learnings/example.md", "Decision: safe.\n")
            (root / ".trail" / "local").mkdir(exist_ok=True)
            (root / ".trail" / "learnings" / "escape.md").symlink_to(
                Path(directory).parent / "outside.md"
            )
            with mock.patch.object(
                check_trail, "_git_paths", return_value={".trail/local/user.md"}
            ):
                diagnostics = check_trail.check(root)
        reasons = {item.reason for item in diagnostics}
        self.assertIn("private Trail cache must not be tracked", reasons)
        self.assertIn("symlink escapes repository", reasons)

    def test_backticks_do_not_hide_hostnames(self):
        diagnostics = self.run_check(
            "---\ntitle: Example\ndate: 2026-10-19\nauthor: Quasarr\n"
            "touches:\n  - quasarr/__init__.py\n---\nUse `source.invalid`.\n"
        )
        self.assertTrue(any("domain-like" in item.reason for item in diagnostics))

    def test_staged_content_is_checked_when_trail_directory_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch.object(
                    check_trail,
                    "_git_paths",
                    return_value={".trail/local/cache.json"},
                ),
            ):
                diagnostics = check_trail.check(root)
        self.assertIn(
            "private Trail cache must not be tracked",
            {item.reason for item in diagnostics},
        )

    def test_requires_complete_frontmatter_and_nonempty_touches(self):
        diagnostics = self.run_check(
            "---\nauthor: Quasarr\ntouches:\n---\nDecision: safe.\n"
        )
        reasons = {item.reason for item in diagnostics}
        self.assertIn("frontmatter requires title", reasons)
        self.assertIn("frontmatter requires date", reasons)
        self.assertIn("frontmatter touches must contain a path", reasons)

    def test_scans_staged_blob_when_worktree_is_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(
                root,
                ".trail/learnings/example.md",
                "---\ntitle: Example\ndate: 2026-10-19\nauthor: Quasarr\ntouches:\n  - quasarr/__init__.py\n---\npassword: staged_value\n",
            )
            self.write(root, "quasarr/__init__.py", "")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "add", ".trail", "quasarr"], check=True
            )
            self.write(
                root,
                ".trail/learnings/example.md",
                "---\ntitle: Example\ndate: 2026-10-19\nauthor: Quasarr\ntouches:\n  - quasarr/__init__.py\n---\nDecision: safe.\n",
            )
            diagnostics = check_trail.check(root)
        self.assertTrue(
            any("credential assignment" in item.reason for item in diagnostics)
        )

    def test_scans_dirty_worktree_when_index_is_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = "---\ntitle: Example\ndate: 2026-10-19\nauthor: Quasarr\ntouches:\n  - quasarr/__init__.py\n---\nDecision: safe.\n"
            self.write(root, ".trail/learnings/example.md", safe)
            self.write(root, "quasarr/__init__.py", "")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "add", ".trail", "quasarr"], check=True
            )
            self.write(
                root,
                ".trail/learnings/example.md",
                safe.replace("Decision: safe.", "token: working_value"),
            )
            diagnostics = check_trail.check(root)
        self.assertTrue(
            any("credential assignment" in item.reason for item in diagnostics)
        )

    def test_rejects_symlink_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".trail" / "learnings").mkdir(parents=True)
            (root / ".trail" / "learnings" / "linked").symlink_to(
                Path(directory).parent, target_is_directory=True
            )
            diagnostics = check_trail.check(root)
        self.assertTrue(
            any("symlinks are not allowed" in item.reason for item in diagnostics)
        )


if __name__ == "__main__":
    unittest.main()
