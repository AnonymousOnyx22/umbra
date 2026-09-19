"""Named, resumable sessions persisted to ~/.umbra/sessions/*.json."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import ensure_umbra_dir

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class Session:
    name: str
    cwd: str
    model: str
    messages: list[dict] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        allowed = cls.__dataclass_fields__
        clean = {k: v for k, v in data.items() if k in allowed}
        for key in ("name", "cwd", "model"):
            if not clean.get(key):
                clean[key] = ""
        return cls(**clean)


class SessionStore:
    def __init__(self, root: Path | None = None):
        self.dir = root or (ensure_umbra_dir() / "sessions")
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        safe = _SAFE.sub("_", name).strip("_") or "default"
        return self.dir / f"{safe}.json"

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json"))

    def load(self, name: str) -> Session | None:
        p = self._path(name)
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return Session.from_dict(data)

    def save(self, session: Session) -> None:
        session.updated = time.time()
        self._path(session.name).write_text(
            json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def remove(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def new(self, name: str, cwd: str, model: str) -> Session:
        return Session(name=name, cwd=cwd, model=model)