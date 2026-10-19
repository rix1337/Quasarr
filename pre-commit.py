import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

# --- CONFIGURATION ---
VERSION_FILE = Path("quasarr/providers/version.py")
PYPROJECT_FILE = Path("pyproject.toml")


def run(cmd, check=True, capture=False, text=True):
    """Helper to run shell commands comfortably."""
    print(f"⚙️  Exec: {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=capture, text=text)


def get_env(key, default=None):
    return os.environ.get(key, default)


def git_status_has_changes():
    return bool(run(["git", "status", "--porcelain"], capture=True).stdout.strip())


def read_text_preserve_newlines(path):
    with path.open(encoding="utf-8", newline="") as f:
        return f.read()


def write_text_preserve_newlines(path, content):
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(content)


# --- TASKS ---


def task_format():
    print("\n🔍 --- 1. FORMATTING & SYNTAX CHECK ---")

    # Runs Ruff using the rules defined in pyproject.toml
    result = run(["uv", "run", "ruff", "check", "--fix", "."], check=False)

    if result.returncode != 0:
        print("❌ Critical errors or syntax issues found. Fix them before staging.")
        sys.exit(1)

    # Standard formatting (indentation/spacing)
    run(["uv", "run", "ruff", "format", "."], check=False)

    if git_status_has_changes():
        print("✅ Linting fixes applied and staged.")
        run(["git", "add", "."])
        return True

    print("✨ Code style is already perfect.")
    return False


def task_tests():
    print("\n🧪 --- 2. TESTS ---")

    result = run(
        ["uv", "run", "python", "-m", "unittest", "discover", "-s", "tests"],
        check=False,
    )

    if result.returncode != 0:
        print("❌ Test suite failed. Fix the failures before staging.")
        sys.exit(1)

    print("✅ Test suite passed.")


def task_upgrade_deps():
    print("\n📦 --- 3. DEPENDENCIES ---")
    try:
        with open(PYPROJECT_FILE, "rb") as f:
            pyproj = tomllib.load(f)

        def get_pkg_name(dep_str):
            m = re.match(r"^[a-zA-Z0-9_\-\.]+", dep_str)
            return m.group(0) if m else None

        # Main dependencies
        deps = pyproj.get("project", {}).get("dependencies", [])
        if deps:
            pkgs = [get_pkg_name(d) for d in deps if get_pkg_name(d)]
            if pkgs:
                print(f"⬆️  Upgrading main: {pkgs}")
                run(["uv", "add", "--upgrade"] + pkgs, check=False)

        # Groups
        groups = pyproj.get("dependency-groups", {})
        for group, g_deps in groups.items():
            if g_deps:
                pkgs = [get_pkg_name(d) for d in g_deps if get_pkg_name(d)]
                if pkgs:
                    print(f"🏗️  Upgrading group '{group}': {pkgs}")
                    run(
                        ["uv", "add", "--group", group, "--upgrade"] + pkgs, check=False
                    )

        # Lock file
        print("🔒 Refreshing lockfile...")
        run(["uv", "lock", "--upgrade"], check=False)

    except Exception as e:
        print(f"⚠️  Dependency upgrade failed: {e}")

    if git_status_has_changes():
        print("✅ Dependencies updated.")
        run(["git", "add", "."])
        return True
    return False


def task_version_bump():
    print("\n🏷️  --- 4. VERSION CHECK ---")
    new_v = ""

    def get_ver(content):
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        return m.group(1) if m else None

    def bump(v):
        p = v.split(".")
        while len(p) < 3:
            p.append("0")
        try:
            p[-1] = str(int(p[-1]) + 1)
        except Exception:
            p.append("1")
        return ".".join(p)

    def ver_tuple(v):
        try:
            return tuple(map(int, v.split(".")))
        except Exception:
            return (0, 0, 0)

    try:
        print("🌐 Fetching origin/main to compare versions...")

        remote_ref = "origin/main"
        has_origin = (
            subprocess.run(
                ["git", "remote", "get-url", "origin"],
                check=False,
                capture_output=True,
                text=True,
            ).returncode
            == 0
        )

        if has_origin:
            run(["git", "fetch", "origin", "main"], check=False)
            remote_head = subprocess.run(
                ["git", "rev-parse", "--verify", remote_ref],
                check=False,
                capture_output=True,
                text=True,
            )
            if remote_head.returncode != 0:
                print(
                    "ℹ️  origin/main not available. Skipping remote version comparison."
                )
                remote_ref = None
        else:
            print(
                "ℹ️  No 'origin' remote configured. Skipping remote version comparison."
            )
            remote_ref = None

        # Read version directly from freshly fetched origin/main.
        # Do not use merge-base: it can compare against an old ancestor.
        try:
            if remote_ref:
                main_v_content = subprocess.check_output(
                    ["git", "show", f"{remote_ref}:{VERSION_FILE.as_posix()}"],
                    text=True,
                )
                main_v = get_ver(main_v_content)
            else:
                main_v = None
        except Exception:
            main_v = None

        # Read Current Version
        curr_v = get_ver(read_text_preserve_newlines(VERSION_FILE))

        print(f"📊 Main: {main_v} | Current: {curr_v}")

        if main_v and curr_v and ver_tuple(curr_v) <= ver_tuple(main_v):
            new_v = bump(main_v)
            print(f"🚀 Bumping version to: {new_v}")
            content = read_text_preserve_newlines(VERSION_FILE).replace(
                f'"{curr_v}"', f'"{new_v}"', 1
            )
            write_text_preserve_newlines(VERSION_FILE, content)

            run(["git", "add", "."])
            return True, new_v

    except Exception as e:
        print(f"⚠️  Version check warning (non-fatal): {e}")

    return False, new_v


def main():
    is_ci = "--ci" in sys.argv
    is_check = "--check" in sys.argv

    # Validate before any task can stage generated files or push fixes.
    privacy = run([sys.executable, "-X", "utf8", "check_trail.py"], check=False)
    if privacy.returncode != 0:
        print("Trail privacy check failed. Remove private content before staging.")
        sys.exit(1)

    # --- CHECK-ONLY MODE (fork-safe) ---
    # Used for pull requests from forks, where the bot cannot push auto-fixes
    # back to the contributor's branch. Verify only — never mutate, commit,
    # push, or bump. Collect every failure into a checklist (written to the
    # job summary and to pr_check_report.md for the PR-comment workflow), then
    # exit non-zero if anything failed.
    if is_check:
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("changes_pushed=false\n")

        checklist = []  # (passed: bool, label, fix hint)

        # --locked keeps these commands from silently re-syncing uv.lock, so a
        # pyproject.toml change without a matching lock update is surfaced below.
        print("\n🔒 --- LOCKFILE (uv lock --check) ---")
        lock = run(["uv", "lock", "--check"], check=False)
        checklist.append(
            (
                lock.returncode == 0,
                "Lockfile up to date (uv.lock vs pyproject.toml)",
                "Run `uv lock` locally and commit the updated `uv.lock`.",
            )
        )

        print("\n🔍 --- LINT (ruff check) ---")
        lint = run(["uv", "run", "--locked", "ruff", "check", "."], check=False)
        print("\n🎨 --- FORMAT (ruff format --check) ---")
        fmt = run(
            ["uv", "run", "--locked", "ruff", "format", "--check", "."], check=False
        )
        style_ok = lint.returncode == 0 and fmt.returncode == 0
        checklist.append(
            (
                style_ok,
                "Lint & formatting (ruff)",
                "Run `uv run pre-commit.py` locally and commit the result.",
            )
        )

        print("\n🧪 --- TESTS ---")
        test = run(
            [
                "uv",
                "run",
                "--locked",
                "python",
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
            ],
            check=False,
        )
        checklist.append(
            (
                test.returncode == 0,
                "Unit tests",
                "Fix the failing tests (see the workflow log for details).",
            )
        )

        all_ok = all(p for p, _, _ in checklist)
        lines = ["## 🤖 Quasarr PR Checks", ""]
        if all_ok:
            lines.append("✅ All checks passed — nothing to fix.")
        else:
            lines.append("Some checks failed. Please fix and push again:")
            lines.append("")
            for passed, label, hint in checklist:
                box = "x" if passed else " "
                lines.append(
                    f"- [{box}] **{label}**" + ("" if passed else f" — {hint}")
                )
        report = "\n".join(lines) + "\n"

        Path("pr_check_report.md").write_text(report, encoding="utf-8")
        if "GITHUB_STEP_SUMMARY" in os.environ:
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(report)

        print("\n" + report)
        if all_ok:
            print("✨ Check passed.")
            sys.exit(0)
        print("❌ ::error::PR checks failed — see the checklist above.")
        sys.exit(1)

    # Run Tasks. Upgrade dependencies first so the same run validates and
    # formats with the versions it just resolved.
    fixed_deps = task_upgrade_deps()
    fixed_format = task_format()
    task_tests()

    fixed_version, new_v = task_version_bump()

    # --- CI Specific Logic ---
    if is_ci and (fixed_format or fixed_deps or fixed_version):
        print("\n📤 --- 5. PUSH & REPORT ---")

        run(["git", "config", "--global", "user.name", "github-actions[bot]"])
        run(
            [
                "git",
                "config",
                "--global",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com",
            ]
        )

        parts = []
        if fixed_format:
            parts.append("fixed linting")
        if fixed_deps:
            parts.append("upgraded dependencies")
        if fixed_version:
            parts.append(f"increased version to {new_v}")

        msg_body = (
            ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]
        )
        msg = f"chore: 🤖 {msg_body}"

        try:
            run(["git", "commit", "-m", msg])
            target_ref = get_env("TARGET_REF")
            print(f"🔄 Rebase and pushing to {target_ref}...")
            run(["git", "pull", "--rebase", "origin", target_ref], check=False)
            run(["git", "push", "origin", f"HEAD:{target_ref}"])

            if "GITHUB_OUTPUT" in os.environ:
                with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                    f.write("changes_pushed=true\n")
        except subprocess.CalledProcessError as e:
            print(f"❌ ::error::Failed to push fixes. ({e})")
            sys.exit(1)

        pr_num = get_env("PR_NUMBER")

        if not pr_num:
            try:
                pr_json = subprocess.check_output(
                    ["gh", "pr", "list", "--head", target_ref, "--json", "number"],
                    text=True,
                )
                prs = json.loads(pr_json)
                if prs:
                    pr_num = str(prs[0]["number"])
            except:
                pass

        if pr_num:
            print(f"💬 Posting status update to PR #{pr_num}...")
            fixes_list = ""
            if fixed_format:
                fixes_list += "- ✅ **Formatted Code**\n"
            if fixed_deps:
                fixes_list += "- ✅ **Upgraded Dependencies**\n"
            if fixed_version:
                fixes_list += f"- ✅ **Bumped Version** ({new_v})\n"

            body = f"### 🤖 Auto-Fix Applied\nI fixed the following issues:\n{fixes_list}\n"
            body += f"Please run `git pull origin {target_ref}` locally.\n"

            Path("comment.md").write_text(body, encoding="utf-8")
            run(
                ["gh", "pr", "comment", pr_num, "--body-file", "comment.md"],
                check=False,
            )

        workflow_name = get_env("WORKFLOW_NAME")
        dispatch = run(
            [
                "gh",
                "workflow",
                "run",
                workflow_name,
                "--ref",
                target_ref,
                "--field",
                "auto_fix_followup=true",
            ],
            check=False,
        )
        if dispatch.returncode != 0:
            print("❌ ::error::Could not dispatch read-only follow-up workflow.")
            sys.exit(1)

        sys.exit(0)

    else:
        print("\n✨ Clean run. No changes needed.")
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("changes_pushed=false\n")


if __name__ == "__main__":
    main()
