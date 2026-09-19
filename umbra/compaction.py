"""Context-window compaction.

When estimated token usage crosses `compact_ratio` of the context window, older
turns are collapsed into a lightweight summary so the conversation can keep
going. No external summarizer is required: we use a deterministic heuristic
that keeps the newest turns intact.
"""
from __future__ import annotations

from .tokens import messages_tokens


def _summarize(discarded: list[dict]) -> str:
    heads = []
    for m in discarded:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            text = content.strip().replace("\n", " ")
            bodies = text
        else:
            bodies = str(content).replace("\n", " ")
        heads.append(f"[{role}] {bodies[:160]}")
    joined = "\n".join(heads)
    return f"Earlier conversation (compacted to save context):\n{joined[:2500]}"


def maybe_compact(
    messages: list[dict],
    context_window: int,
    ratio: float = 0.7,
) -> tuple[list[dict], bool]:
    """Return (possibly-compacted messages, did_compact).

    Keeps the first pair (system + original opener), the last N turns, and
    folds everything in between into one summary message.
    """
    if not messages:
        return messages, False
    if messages_tokens(messages) < context_window * ratio:
        return messages, False

    keep = 6  # keep the newest N messages
    if len(messages) <= keep + 2:
        return messages, False

    side = [m for m in messages if m.get("role") == "system"]
    body = [m for m in messages if m.get("role") != "system"]
    if len(body) <= keep:
        return messages, False

    head = body[: len(body) - keep]
    tail = body[len(body) - keep:]

    summary = _summarize(head)
    compacted = side + [{"role": "user", "content": summary}] + tail
    return compacted, True