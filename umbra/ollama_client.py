"""Ollama client wrapper: streaming chat with optional function-calling.

The `ollama` Python package is imported lazily so umbra can still start with a
helpful error when the dependency is missing.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from .tools import TOOL_SCHEMA, normalize_calls

_TOOLS_FALLBACK_HINTS = (
    "tool", "function", "unsupported", "schema", "template",
    "does not support", "unknown field", "not implemented",
)


def _looks_like_tools_rejection(exc: Exception) -> bool:
    """True when the error sounds like the model refusing the `tools=` param.

    Only these fall back to the text protocol. A connection error, auth
    failure or missing model must surface as-is instead of getting masked by a
    mystery retry.
    """
    text = f"{exc}".lower()
    return any(hint in text for hint in _TOOLS_FALLBACK_HINTS)


class OllamaEngine:
    def __init__(self, host: str, model: str):
        self.host = host
        self.model = model
        self._ollama = None
        # Flipped by the UI on interrupt; the stream loop checks it per token.
        self.cancelled = False
        self.last_native = False

    def _client(self):
        if self._ollama is None:
            import ollama  # lazy import

            self._ollama = ollama.Client(host=self.host)
        return self._ollama

    def _raise_dep_missing(self, exc: Exception) -> Exception:
        if "No module named 'ollama'" in str(exc):
            return RuntimeError(
                "the 'ollama' python package is not installed - run: pip install -e ."
            )
        return exc

    def _stream_blocking(
        self,
        messages: list[dict],
        on_chunk: Callable[[str], None],
        tools: bool = True,
    ):
        client = self._client()
        kwargs = dict(model=self.model, messages=messages, stream=True)
        if tools:
            kwargs["tools"] = TOOL_SCHEMA
        stream = client.chat(**kwargs)
        final: dict = {}
        whole: list[str] = []
        tool_calls = []
        for part in stream:
            if self.cancelled:
                # Stop pulling tokens; closing the generator ends generation.
                try:
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
                break
            msg = part.get("message", {})
            content = msg.get("content")
            if content:
                whole.append(content)
                on_chunk(content)
            if msg.get("tool_calls"):
                tool_calls = msg["tool_calls"]
            final = msg
        # `final` is only the LAST chunk, so its content is the last token.
        # The text protocol needs the whole reply to find tool tags in it.
        final = dict(final)
        final["content"] = "".join(whole)
        final["tool_calls"] = tool_calls
        return final

    async def chat(
        self,
        messages: list[dict],
        on_chunk: Callable[[str], None],
        tools: bool = True,
    ) -> tuple[list[dict], str]:
        """Stream a turn. Returns (normalized tool_calls, full assistant text).

        Some local models reject the `tools=` request (no function-calling
        support). Retry once without native tools and rely on the parsed XML
        text protocol instead.
        """
        self.cancelled = False
        self.last_native = False
        tools_enabled = tools
        final = {}
        for attempt in range(2):
            try:
                final = await asyncio.to_thread(
                    self._stream_blocking, messages, on_chunk, tools_enabled
                )
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 0 and tools_enabled and _looks_like_tools_rejection(exc):
                    tools_enabled = False
                    continue
                raise self._raise_dep_missing(exc) from exc
        calls = normalize_calls(final.get("tool_calls", []))
        self.last_native = bool(calls)
        return calls, final.get("content", "") or ""
    def list_models(self) -> list[str]:
        """Model names available on the Ollama host (empty list on failure)."""
        try:
            data = self._client().list()
        except Exception:
            return []
        models = data.get("models", []) if isinstance(data, dict) else getattr(data, "models", [])
        names = []
        for item in models:
            name = item.get("model") or item.get("name") if isinstance(item, dict) else \
                getattr(item, "model", None) or getattr(item, "name", None)
            if name:
                names.append(str(name))
        return names
