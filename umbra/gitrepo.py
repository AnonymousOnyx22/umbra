"""Git integration: repo root detection and opt-in `git init`.

umbra refuses file edits / shell commands in a directory that isn't a git repo.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for a .git directory."""
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def git_init(repo_path: Path, workdir: Path | None = None) -> tuple[int, str]:
    """Run `git init` in repo_path (which is typically also the workdir)."""
    return subprocess.Popen(
        ["git", "init"],
        cwd=str(workdir or repo_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).communicate()


def is_repo(repo_path: Path | None) -> bool:
    return repo_path is not None


def list_files(repo_root: Path, workdir: Path) -> list[Path]:
    """List tracked + untracked non-ignored files, respecting .gitignore.

    Uses `git ls-files -c -o --exclude-standard`. Falls back to a manual walk
    that skips the usual junk directories when git misbehaves.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-c", "-o", "--exclude-standard"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode == 0:
            files = []
            for line in out.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                p = repo_root / line
                if p.is_file():
                    files.append(p)
            return files
    except Exception:
        pass

    skips = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
    files: list[Path] = []
    for p in workdir.rglob("*"):
        if any(part in skips for part in p.parts):
            continue
        if p.is_file():
            files.append(p)
    return files

def current_branch(repo_root: Path | None) -> str | None:
    """Short branch name for the footer, or None outside a repo."""
    if repo_root is None:
        return None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    name = out.stdout.strip()
    return name or None
