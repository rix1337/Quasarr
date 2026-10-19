#!/usr/bin/env python3
"""Static privacy gate for repository Trail learnings."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOWED_FILE = re.compile(r"\.trail/learnings/[^/]+\.md\Z")
PRIVATE_PREFIXES = (".trail/local/", ".trail/cache/", ".trail/.cache/")
DOMAIN = re.compile(r"(?i)(?:https?://|(?:www\.)?)[a-z0-9-]+(?:\.[a-z0-9-]+)+")
FILENAME_SUFFIX = re.compile(r"(?i)\.(?:py|md|toml|ya?ml|json|txt|sh|js|ts|lock)\Z")
EMAIL = re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b")
POSIX_PATH = re.compile(r"(?<![\w.])/(?:[^\s`'\"<>),;]+/)*[^\s`'\"<>),;]+")
HOME_PATH = re.compile(r"(?<![\w.])~[/\\][^\s`'\"<>),;]+")
WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:[\\/][^\s`'\"<>),;]+")
CREDENTIAL = re.compile(
    r"(?im)\b(?:api[_-]?key|access[_-]?key|auth(?:entication)?|password|passwd|secret|token|webhook)\b\s*[:=]\s*[^\s#`]+"
)
TOUCHES = re.compile(r"^\s*touches\s*:\s*(.*)\s*$")
FRONTMATTER_KEY = re.compile(r"^\s*([A-Za-z][\w-]*)\s*:\s*(.*?)\s*$")


@dataclass(frozen=True)
class Diagnostic:
    path: str
    reason: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", self.path):
            object.__setattr__(self, "path", ".trail/<rejected-path>")

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


def _git_paths(repo: Path, cached: bool) -> set[str]:
    command = ["git", "-C", str(repo), "ls-files", "-z"]
    if cached:
        command.append("--cached")
    command.append("--")
    command.append(".trail")
    try:
        output = subprocess.run(command, check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {
        item.decode("utf-8", "surrogateescape") for item in output.split(b"\0") if item
    }


def _files(repo: Path) -> tuple[list[tuple[str, Path]], set[str]]:
    root = repo / ".trail"
    tracked = _git_paths(repo, cached=True)
    entries: list[tuple[str, Path]] = []
    if not root.exists():
        return [(relative, repo / relative) for relative in tracked], tracked
    for current, dirs, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(dirs):
            path = current_path / name
            if path.is_symlink():
                entries.append((path.relative_to(repo).as_posix(), path))
                dirs.remove(name)
        dirs[:] = [
            name
            for name in dirs
            if name not in {"__pycache__", "local", "cache", ".cache"}
        ]
        for name in names:
            path = current_path / name
            relative = path.relative_to(repo).as_posix()
            entries.append((relative, path))
    known = {relative for relative, _ in entries}
    for relative in tracked - known:
        entries.append((relative, repo / relative))
    return entries, tracked


def _private(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PRIVATE_PREFIXES)


def _safe_relative(path_value: str, repo: Path) -> bool:
    value = path_value.strip().strip("'\"")
    if (
        not value
        or "*" in value
        or value in {".", ".."}
        or "/../" in f"/{value}/"
        or value.startswith("../")
    ):
        return False
    if value.startswith(("/", "~")) or (len(value) > 1 and value[1] == ":"):
        return False
    try:
        target = (repo / value).resolve()
        target.relative_to(repo.resolve())
    except (OSError, ValueError):
        return False
    return target.exists()


def _frontmatter(text: str, path: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return (
            [Diagnostic(path, "learning requires frontmatter")]
            if path.startswith(".trail/learnings/")
            else []
        )
    end = next(
        (index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"),
        None,
    )
    if end is None:
        return [Diagnostic(path, "unterminated frontmatter")]
    keys: set[str] = set()
    in_touches = False
    for line in lines[1:end]:
        match = FRONTMATTER_KEY.match(line)
        if not match:
            if line.strip() and not (in_touches and line.strip().startswith("-")):
                diagnostics.append(
                    Diagnostic(path, "frontmatter contains unrecognized metadata")
                )
            continue
        key = match.group(1).lower()
        keys.add(key)
        in_touches = key == "touches"
        if not match.group(2).strip() and key != "touches":
            diagnostics.append(Diagnostic(path, "frontmatter value is empty"))
        if key == "author" and match.group(2).strip().strip("'\"") != "Quasarr":
            diagnostics.append(
                Diagnostic(path, "frontmatter author must be generic Quasarr")
            )
        if key not in {"title", "date", "author", "touches"}:
            diagnostics.append(Diagnostic(path, "frontmatter key is not allowed"))
    if path.startswith(".trail/learnings/"):
        for required in ("title", "date", "author", "touches"):
            if required not in keys:
                diagnostics.append(Diagnostic(path, f"frontmatter requires {required}"))
        if "touches" in keys and not _touch_paths(text):
            diagnostics.append(
                Diagnostic(path, "frontmatter touches must contain a path")
            )
    return diagnostics


def _touch_paths(text: str) -> list[str]:
    values: list[str] = []
    active = False
    for line in text.splitlines():
        match = TOUCHES.match(line)
        if match:
            active = True
            inline = match.group(1).strip()
            if inline.startswith("[") and inline.endswith("]"):
                values.extend(
                    part.strip().strip("'\"") for part in inline[1:-1].split(",")
                )
            continue
        if active:
            if line.startswith((" ", "\t")) and line.strip().startswith("-"):
                values.append(line.strip()[1:].strip().strip("'\""))
            elif line.strip() and not line.startswith((" ", "\t")):
                active = False
    return values


def _read_content(repo: Path, path: str, tracked: bool) -> str:
    if tracked:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "show", f":{path}"],
                check=True,
                capture_output=True,
            )
            return result.stdout.decode("utf-8")
        except (OSError, UnicodeError, subprocess.CalledProcessError):
            pass
    return (repo / path).read_text(encoding="utf-8")


def _content_diagnostics(repo: Path, path: str, tracked: bool) -> list[Diagnostic]:
    try:
        text = _read_content(repo, path, tracked)
    except (OSError, UnicodeError):
        return [Diagnostic(path, "file is unreadable text")]
    diagnostics = _frontmatter(text, path)
    if EMAIL.search(text):
        diagnostics.append(Diagnostic(path, "email address is not allowed"))

    def domain_allowed(match: re.Match[str]) -> bool:
        value = match.group(0)
        if value.lower().startswith(("http://", "https://", "www.")):
            return False
        if not FILENAME_SUFFIX.search(value):
            return False
        start = match.start()
        while start and re.match(r"[A-Za-z0-9_./-]", text[start - 1]):
            start -= 1
        candidate = text[start : match.end()].strip("`'\"")
        return (repo / candidate).is_file()

    domain_match = next(
        (match for match in DOMAIN.finditer(text) if not domain_allowed(match)),
        None,
    )
    if domain_match:
        diagnostics.append(Diagnostic(path, "URL or domain-like value is not allowed"))
    if POSIX_PATH.search(text) or HOME_PATH.search(text) or WINDOWS_PATH.search(text):
        diagnostics.append(Diagnostic(path, "absolute path is not allowed"))
    if CREDENTIAL.search(text):
        diagnostics.append(Diagnostic(path, "credential assignment is not allowed"))
    for value in _touch_paths(text):
        if not _safe_relative(value, repo):
            diagnostics.append(
                Diagnostic(path, "touches contains an unsafe or nonexistent path")
            )
    return diagnostics


def check(repo: Path | str = ".") -> list[Diagnostic]:
    """Return privacy diagnostics for `.trail` under *repo*."""
    repo = Path(repo).resolve()
    trail_root = repo / ".trail"
    if trail_root.is_symlink():
        return [Diagnostic(".trail", "symlinks are not allowed in Trail content")]
    entries, tracked = _files(repo)
    diagnostics: list[Diagnostic] = []
    for relative, path in entries:
        if _private(relative) and relative not in tracked:
            continue
        if path.is_symlink():
            diagnostics.append(
                Diagnostic(relative, "symlinks are not allowed in Trail content")
            )
            try:
                path.resolve().relative_to(repo)
            except ValueError:
                diagnostics.append(Diagnostic(relative, "symlink escapes repository"))
                continue
            continue
        if (
            relative not in tracked
            and not ALLOWED_FILE.fullmatch(relative)
            and relative != ".trail/.gitignore"
        ):
            diagnostics.append(
                Diagnostic(relative, "file is outside allowed Trail content")
            )
            continue
        if relative in tracked and _private(relative):
            diagnostics.append(
                Diagnostic(relative, "private Trail cache must not be tracked")
            )
            continue
        if not (ALLOWED_FILE.fullmatch(relative) or relative == ".trail/.gitignore"):
            diagnostics.append(
                Diagnostic(relative, "file is outside allowed Trail content")
            )
            continue
        diagnostics.extend(_content_diagnostics(repo, relative, relative in tracked))
        if relative in tracked and path.is_file() and not path.is_symlink():
            diagnostics.extend(_content_diagnostics(repo, relative, False))
    return diagnostics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check Trail files for private content"
    )
    parser.add_argument("repo", nargs="?", default=".")
    args = parser.parse_args(argv)
    diagnostics = check(args.repo)
    for diagnostic in diagnostics:
        print(diagnostic, file=sys.stderr)
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
