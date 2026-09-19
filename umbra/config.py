"""Configuration loading for umbra (~/.umbra/config.toml).

No external deps: standard-library tomllib (Python >= 3.11).
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "huihui_ai/qwen2.5-coder-abliterate:7b"
DEFAULT_CONTEXT_WINDOW = 32768

DEFAULT_CONFIG = {
    "host": DEFAULT_HOST,
    "model": DEFAULT_MODEL,
    "context_window": DEFAULT_CONTEXT_WINDOW,
    "discovery_top_n": 6,
    "discovery_max_file_chars": 200_000,
    "max_tool_iterations": 8,
    "compact_ratio": 0.7,
    "default_session": "default",
    "auto_approve": False,
    "require_git": True,
    "command_timeout": 120,
}


@dataclass
class Config:
    host: str = DEFAULT_HOST
    model: str = DEFAULT_MODEL
    context_window: int = DEFAULT_CONTEXT_WINDOW
    discovery_top_n: int = 6
    discovery_max_file_chars: int = 200_000
    max_tool_iterations: int = 8
    compact_ratio: float = 0.7
    default_session: str = "default"
    auto_approve: bool = False
    require_git: bool = True
    command_timeout: int = 120
    raw: dict = field(default_factory=dict)


def config_path() -> Path:
    return Path(os.environ.get("UMBRA_CONFIG", Path.home() / ".umbra" / "config.toml"))


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    merged = dict(DEFAULT_CONFIG)
    if path.is_file():
        with open(path, "rb") as fh:
            user = tomllib.load(fh)
        for key in merged:
            if key in user:
                merged[key] = user[key]
    cfg = Config(**{k: v for k, v in merged.items() if k != "raw"})
    cfg.raw = merged
    return cfg


def write_setting(key: str, value, path: Path | None = None) -> Path:
    """Persist one key to config.toml, leaving the rest of the file alone."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    literal = {True: "true", False: "false"}.get(value)
    if literal is None:
        literal = str(value) if isinstance(value, (int, float)) else f'"{value}"'
    lines = []
    if path.is_file():
        lines = [
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith(f"{key} ")
            and not line.strip().startswith(f"{key}=")
        ]
    lines.append(f"{key} = {literal}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def ensure_umbra_dir() -> Path:
    d = Path.home() / ".umbra"
    d.mkdir(parents=True, exist_ok=True)
    return d