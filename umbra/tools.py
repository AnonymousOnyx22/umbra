"""Tool layer.

Two entry routes:

1. Native function-calling (Ollama `tools=`), where the model returns
   structured `tool_calls`.
2. A parsed text protocol (`<read path="x"/>`, `<grep pattern="x"/>`,
   `<ls path="x"/>`, `<edit path="x">...</edit>`, `<run>cmd</run>`) used when
   the model has no function-calling support (the abliterate 7b default).

Every edit is applied as a unified diff *after* explicit user confirmation
unless `--yes`/`--yolo` was passed. Shell commands show a preview +
confirmation too.

With `require_git=False` (what `--yolo` sets) the repo gate is lifted: edits
and commands run anywhere on the machine. Overwrites are always copied to
~/.umbra/backups first, so `/undo` can put a file back.
"""
from __future__ import annotations

import difflib
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a file and return its contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "relative or absolute file path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search the repo for a regex pattern in code files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "description": "optional subdirectory"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "List a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Replace a file's entire contents with new contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "the new full file contents"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cd",
            "description": (
                "Change the working directory. Use this when the user asks to "
                "work in, go to, or open another folder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "the directory to move to"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run",
            "description": "Run a shell command in the working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
]

_TEXT_TOOLS = [
    (re.compile(r"<read\s+path='([^']+)'\s*/>", re.I), "read"),
    (re.compile(r'<read\s+path="([^"]+)"\s*/>', re.I), "read"),
    (re.compile(r"<grep\s+pattern='([^']+)'\s*path='([^']+)'\s*/>", re.I), "grep"),
    (re.compile(r'<grep\s+pattern="([^"]+)"\s*path="([^"]+)"\s*/>', re.I), "grep"),
    (re.compile(r"<grep\s+pattern='([^']+)'\s*/>", re.I), "grep"),
    (re.compile(r'<grep\s+pattern="([^"]+)"\s*/>', re.I), "grep"),
    (re.compile(r"<ls\s+path='([^']+)'\s*/>", re.I), "ls"),
    (re.compile(r'<ls\s+path="([^"]+)"\s*/>', re.I), "ls"),
    (re.compile(r"<cd\s+path='([^']+)'\s*/>", re.I), "cd"),
    (re.compile(r'<cd\s+path="([^"]+)"\s*/>', re.I), "cd"),
    (re.compile(r"<edit\s+path='([^']+)'\s*>([\s\S]*?)</edit>", re.I), "edit"),
    (re.compile(r'<edit\s+path="([^"]+)"\s*>([\s\S]*?)</edit>', re.I), "edit"),
    (re.compile(r"<run>([\s\S]*?)</run>", re.I), "run"),
    (re.compile(r"<run\s+command='([^']+)'\s*/>", re.I), "run"),
    (re.compile(r'<run\s+command="([^"]+)"\s*/>', re.I), "run"),
]


def parse_text_tools(text: str) -> list[dict]:
    """Parse text-protocol tool calls out of model output."""
    matches = []
    for rx, name in _TEXT_TOOLS:
        for m in rx.finditer(text):
            matches.append((m.start(), name, m))
    calls: list[dict] = []
    for _, name, m in sorted(matches, key=lambda item: item[0]):
        groups = list(m.groups())
        if name == "grep":
            calls.append({"name": "grep", "arguments": {
                "pattern": groups[0], "path": groups[1] if len(groups) > 1 else "."}})
        elif name == "edit":
            calls.append({"name": "edit", "arguments": {"path": groups[0], "content": groups[1]}})
        else:
            key = "path" if name in ("read", "ls", "cd") else "command"
            calls.append({"name": name, "arguments": {key: groups[0]}})
    return calls


def strip_tool_tags(text: str) -> str:
    """Remove tool-protocol tags from a reply, leaving the prose behind.

    The tags are rendered as rows in the activity feed, so showing the raw XML
    as well is just noise.
    """
    for rx, _name in _TEXT_TOOLS:
        text = rx.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_calls(tool_calls) -> list[dict]:
    """Normalize Ollama tool_calls into [{name, arguments}]."""
    out = []
    for call in (tool_calls or []):
        fn = call.get("function", call)
        try:
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = _try_json(args)
        except Exception:
            args = {"detail": str(fn)}
        out.append({"name": fn.get("name", ""), "arguments": args or {}})
    return out


def _try_json(s: str) -> dict:
    import json

    try:
        return json.loads(s)
    except Exception:
        return {"raw": s}


def _resolve(root: Path, workdir: Path, rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute():
        return p.resolve()
    return (workdir / rel).resolve()


def backup_dir() -> Path:
    from .config import ensure_umbra_dir

    d = ensure_umbra_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_file(path: Path) -> str | None:
    """Copy `path` aside before it is overwritten. Returns the copy's path."""
    if not path.is_file():
        return None
    import shutil
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(path))
    dest = backup_dir() / f"{uuid.uuid4().hex}_{safe[-120:]}"
    shutil.copy2(path, dest)
    return str(dest)


_MAX_READ = 120_000
_MAX_RESULT = 60_000


def _clip(text: str) -> str:
    if len(text) > _MAX_RESULT:
        return text[:_MAX_RESULT] + f"\n... (truncated, {len(text)} chars)"
    return text


class ToolRunner:
    def __init__(self, root: Path, workdir: Path, *, require_git: bool = True,
                 timeout: int | None = 120):
        self.root = root
        self.workdir = workdir
        self.require_git = require_git
        self.timeout = timeout

    def _check_in_repo(self, path: Path) -> None:
        if not self.require_git:
            return
        if self.root is None:
            raise RuntimeError("no git repository detected - run git init first")
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise RuntimeError(f"edit target is outside the git repository: {path}")

    def read(self, path: str) -> str:
        p = _resolve(self.root or self.workdir, self.workdir, path)
        if not p.is_file():
            return f"ERROR: no such file: {p}"
        try:
            return _clip(p.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            return f"ERROR reading {p}: {exc}"

    def ls(self, path: str) -> str:
        p = _resolve(self.root or self.workdir, self.workdir, path or ".")
        if not p.is_dir():
            return f"ERROR: no such directory: {p}"
        try:
            entries = []
            for child in sorted(p.iterdir()):
                entries.append(child.name + ("/" if child.is_dir() else ""))
            return "\n".join(entries) or "(empty)"
        except OSError as exc:
            return f"ERROR listing {p}: {exc}"

    def grep(self, pattern: str, path: str = "") -> str:
        from .gitrepo import list_files

        base = _resolve(self.root or self.workdir, self.workdir, path or ".")
        files = list_files(self.root, base) if self.root else list(base.rglob("*"))
        try:
            rx = __import__("re").compile(pattern)
        except Exception as exc:
            return f"ERROR: bad pattern: {exc}"
        hits = []
        for f in files:
            if not f.is_file() or (self.root and not str(f).startswith(str(self.root))):
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        rel = f.relative_to(self.root) if self.root else f
                        hits.append(f"{rel}:{i}: {line[:220]}")
                        if len(hits) > 200:
                            break
            except OSError:
                continue
            if len(hits) > 200:
                break
        return "\n".join(hits) or f"no matches for {pattern!r}"

    def edit(self, path: str, content: str) -> dict:
        p = _resolve(self.root or self.workdir, self.workdir, path)
        self._check_in_repo(p)
        old = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
        if old == content:
            return {"status": "unchanged", "diff": "", "path": str(p)}
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=str(p),
                tofile=str(p),
            )
        )
        return {"status": "pending", "diff": diff, "path": str(p), "content": content,
                "old": old, "existed": p.is_file()}

    def apply_edit(self, path: str, content: str, *, expected_old: str | None = None,
                   expected_exists: bool | None = None) -> str | None:
        """Write the file, returning the backup path of what was there before."""
        p = _resolve(self.root or self.workdir, self.workdir, path)
        self._check_in_repo(p)
        exists = p.is_file()
        if expected_exists is not None and exists != expected_exists:
            raise RuntimeError(f"file changed since preview: {p}")
        if expected_old is not None and exists and p.read_text(encoding="utf-8", errors="replace") != expected_old:
            raise RuntimeError(f"file changed since preview: {p}")
        backup = backup_file(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                             dir=p.parent, prefix=f".{p.name}.",
                                             suffix=".tmp", delete=False) as fh:
                temp_path = Path(fh.name)
                fh.write(content)
            if exists:
                os.chmod(temp_path, p.stat().st_mode)
            os.replace(temp_path, p)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return backup

    def run(self, command: str) -> str:
        if self.require_git and self.root is None:
            raise RuntimeError("no git repository detected - run git init first")
        try:
            proc = subprocess.run(
                command,
                cwd=str(self.workdir),
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return f"[timeout after {self.timeout}s] {command}"
        out = proc.stdout + ("\n" if proc.stdout and proc.stderr else "") + proc.stderr
        label = f"exit {proc.returncode}"
        return f"[{label}]\n{_clip(out or '(no output)')}"

    def execute(self, call: dict) -> str:
        name = call.get("name", "")
        args = call.get("arguments", {}) or {}
        if name == "read":
            return self.read(str(args.get("path", "")))
        if name == "ls":
            return self.ls(str(args.get("path", ".")))
        if name == "grep":
            return self.grep(str(args.get("pattern", "")), str(args.get("path", "") or "."))
        if name == "edit":
            return str(self.edit(str(args.get("path", "")), str(args.get("content", ""))))
        if name == "run":
            return self.run(str(args.get("command", "")))
        return f"ERROR: unknown tool {name}"
