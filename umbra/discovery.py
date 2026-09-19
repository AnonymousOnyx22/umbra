"""Auto-discovery of relevant files for a user message.

Pipeline: keyword extraction -> walk repo (gitignore-aware) -> rank by
filename + content matches -> return the top-N paths. No manual /add needed.
"""
from __future__ import annotations

import re
from pathlib import Path

from .gitrepo import list_files

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in",
    "on", "at", "for", "and", "or", "but", "with", "by", "from", "as", "it",
    "this", "that", "these", "those", "my", "me", "i", "you", "your", "we",
    "our", "they", "them", "he", "she", "his", "her", "how", "why", "what",
    "which", "where", "when", "who", "please", "can", "could", "would",
    "should", "will", "do", "does", "did", "just", "about", "into", "over",
    "under", "than", "then", "there", "here", "have", "has", "had", "not",
    "so", "if", "else", "off", "out", "up", "down", "file", "files", "code",
    "function", "class", "fix", "run", "write", "read", "show", "tell",
    # extension / tech noise
    "py", "js", "ts", "go", "rs", "cs", "json", "toml", "yaml", "yml", "txt",
    "md", "html", "css", "git", "exe", "lib", "src", "mod", "app", "config",
    "example", "test", "tests", "util", "utils", "helper",
}

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")


def extract_keywords(text: str, n: int = 8) -> list[str]:
    words: list[str] = []
    for w in _TOKEN.findall(text.lower()):
        if len(w) <= 1 or w in _STOPWORDS:
            continue
        words.append(w)
    seen: dict[str, int] = {}
    for w in words:
        seen[w] = seen.get(w, 0) + 1
    ranked = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))
    # keep distinct words only
    return [w for w, _ in ranked[:n]]


def _content_hits(path: Path, kws: list[str], max_chars: int) -> int:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    if len(raw) > max_chars:
        raw = raw[:max_chars]
    low = raw.lower()
    return sum(low.count(kw) for kw in kws)


def discover_for_message(
    workdir: Path,
    repo_root: Path | None,
    message: str,
    top_n: int = 6,
    max_file_chars: int = 200_000,
) -> list[Path]:
    kws = extract_keywords(message)
    if not kws:
        return []
    if repo_root is None:
        return []
    files = list_files(repo_root, workdir)

    scored: list[tuple[Path, float]] = []
    for f in files:
        if f.suffix.lower() in {".pyc", ".lock", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico"}:
            continue
        fname = f.name.lower()
        name_hits = sum(fname.count(kw) for kw in kws)
        content_hits = _content_hits(f, kws, max_file_chars)
        score = name_hits * 5.0 + content_hits
        if score > 0:
            scored.append((f, score))

    scored.sort(key=lambda t: -t[1])
    return [f for f, _ in scored[:top_n]]