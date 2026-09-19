"""Ollama client wrapper: streaming chat with optional function-calling.

The `ollama` Python package is imported lazily so umbra can still start with a
helpful error when the dependency is missing.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from .tools import TOOL_SCHEMA, normalize_calls


class OllamaEngine:
    def __init__(self, host: str, model: str):
        self.host = host
        self.model = model
        self._ollama = None

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
        final = {}
        for part in stream:
            msg = part.get("message", {})
            content = msg.get("content")
            if content:
                on_chunk(content)
            final = msg
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
        tools_enabled = tools
        final = {}
        for attempt in range(2):
            try:
                final = await asyncio.to_thread(
                    self._stream_blocking, messages, on_chunk, tools_enabled
                )
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 0 and tools_enabled:
                    tools_enabled = False
                    continue
                raise self._raise_dep_missing(exc) from exc
        calls = normalize_calls(final.get("tool_calls", []))
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
