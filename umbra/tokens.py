"""Token estimation without heavyweight tokenizers.

Approximation: 1 token ≈ 4 characters (English-leaning heuristic, fine for a
context-budget indicator). The sidebar always shows it as an estimate.
"""
from __future__ import annotations

MESSAGES = 0

_TAX = 12  # per-message framing overhead in "tokens"


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def message_tokens(message: dict) -> int:
    base = _TAX
    for key in ("role", "name"):
        base += estimate_tokens(str(message.get(key, "")))
    content = message.get("content")
    if isinstance(content, str):
        base += estimate_tokens(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                base += estimate_tokens(str(part.get("text") or part.get("content") or ""))
    return base


def messages_tokens(messages: list[dict]) -> int:
    return sum(message_tokens(m) for m in messages)