"""The activity feed: every action the model takes, categorized and collapsed.

Codex-style rows. Each tool call is one line you can read at a glance —
category chip, target, and a one-line result summary with how long it took —
and one click (or `enter`) expands the full output underneath. Runs of the
same category collapse into a single group row, so a burst of twelve reads
doesn't bury the answer.

Rows live-update while the call is in flight: a spinner and a running clock,
replaced by the summary the moment it lands.
"""
from __future__ import annotations

import time

from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Label, Static

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# category -> (chip, color, plural noun for group rows)
CATEGORIES: dict[str, tuple[str, str, str]] = {
    "read":    ("read",    "#67c01e", "files read"),
    "grep":    ("search",  "#e8a33d", "searches"),
    "ls":      ("list",    "#e8a33d", "listings"),
    "edit":    ("edit",    "#e05561", "edits"),
    "run":     ("run",     "#5aa7e5", "commands"),
    "context": ("context", "#67c01e", "files pulled in"),
    "tool":    ("tool",    "#5b8ff5", "tool calls"),
    "think":   ("think",   "#a693f0", "thoughts"),
    "info":    ("info",    "#6c7a89", "notes"),
    "warn":    ("warn",    "#ffb454", "warnings"),
    "error":   ("error",   "#e05561", "errors"),
}

MUTED = "#6c7a89"
DIM = "#4a4a52"


def _esc(text: str) -> str:
    """Titles carry paths, patterns and commands - never treat them as markup."""
    return text.replace("[", "\\[")


def chip(prefix: str) -> tuple[str, str]:
    label, color, _ = CATEGORIES.get(prefix, (prefix, "#9aa3b0", prefix))
    return label, color


def human_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


class Activity(Vertical):
    """One collapsible action row.

    `title` is the target (a path, a pattern, a command). `summary` is the
    result in a few words. Body text is hidden until the row is expanded.
    """

    collapsed = reactive(True)

    def __init__(self, prefix: str, title: str, body: str = "", *,
                 summary: str = "", expanded: bool = False, running: bool = False,
                 body_markup: bool = False):
        super().__init__(classes="activity")
        self.prefix = prefix
        self.title_text = title
        self.summary = summary
        self.running = running
        self.started = time.monotonic()
        self.elapsed: float | None = None
        self._body_text = body
        self._head = Label("", classes="act-head", markup=True)
        self._body = Static(body, markup=body_markup,
                            classes=f"act-body bb-{prefix}")
        self._frame = 0
        self._timer = None
        self.collapsed = not expanded

    def compose(self):
        yield self._head
        yield self._body

    def on_mount(self):
        if self.running:
            self._timer = self.set_interval(1 / 12, self._tick)
        self._refresh()

    def _tick(self):
        self._frame = (self._frame + 1) % len(SPINNER)
        self._refresh()

    def finish(self, summary: str = "", body: str | None = None,
               prefix: str | None = None):
        """Swap the spinner for the result."""
        self.running = False
        self.elapsed = time.monotonic() - self.started
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if summary:
            self.summary = summary
        if prefix:
            self.prefix = prefix
        if body is not None:
            self._body_text = body
            self._body.update(body)
        self._refresh()

    def set_body(self, body: str):
        self._body_text = body
        self._body.update(body)
        self._refresh()

    def watch_collapsed(self, _collapsed: bool):
        self._refresh()

    def _refresh(self):
        if not hasattr(self, "_head"):
            return
        label, color = chip(self.prefix)
        has_body = bool(self._body_text.strip())
        if self.running:
            mark = f"[{color}]{SPINNER[self._frame]}[/{color}]"
        elif has_body:
            caret = "▾" if not self.collapsed else "▸"
            mark = f"[{DIM}]{caret}[/{DIM}]"
        else:
            mark = f"[{DIM}]·[/{DIM}]"

        line = f"{mark} [{color}]{label:<7}[/{color}] {_esc(self.title_text)}"
        tail = []
        if self.summary:
            tail.append(_esc(self.summary))
        if self.elapsed is not None and self.elapsed >= 0.05:
            tail.append(human_duration(self.elapsed))
        elif self.running:
            tail.append(human_duration(time.monotonic() - self.started))
        if tail:
            line += f"  [{DIM}]·[/{DIM}] [{MUTED}]{'  '.join(tail)}[/{MUTED}]"
        self._head.update(line)
        self._body.display = (not self.collapsed) and has_body

    def toggle(self):
        if self._body_text.strip():
            self.collapsed = not self.collapsed

    def on_click(self, event):
        if getattr(event, "button", 1) == 3:
            self.app.copy_block(self)
            event.stop()
            return
        self.toggle()

    @property
    def copy_text(self) -> str:
        label, _ = chip(self.prefix)
        return f"{label}  {self.title_text}\n{self._body_text}"


class ActivityGroup(Vertical):
    """A run of same-category rows folded into one line.

    Collapsed it reads `▸ context  6 files pulled in`; expanded it shows every
    row underneath, each still individually expandable.
    """

    collapsed = reactive(True)

    def __init__(self, prefix: str, rows: list[Activity] | None = None, *,
                 expanded: bool = False):
        super().__init__(classes="activity-group")
        self.prefix = prefix
        self.rows: list[Activity] = list(rows or [])
        self._head = Label("", classes="act-head", markup=True)
        self._holder: Vertical | None = None
        self.collapsed = not expanded

    def compose(self):
        yield self._head
        # Rows handed in before mount are composed in directly; Textual can't
        # mount into a container that isn't on screen yet.
        self._holder = Vertical(*self.rows, classes="act-children")
        yield self._holder

    def on_mount(self):
        self._refresh()

    def add(self, row: Activity) -> Activity:
        self.rows.append(row)
        if self._holder is not None and self._holder.is_mounted:
            self._holder.mount(row)
        self._refresh()
        return row

    def watch_collapsed(self, _collapsed: bool):
        self._refresh()

    def _refresh(self):
        if not hasattr(self, "_head"):
            return
        label, color = chip(self.prefix)
        _, _, noun = CATEGORIES.get(self.prefix, (label, color, "items"))
        mark = "▾" if not self.collapsed else "▸"
        count = len(self.rows)
        names = ", ".join(_esc(r.title_text) for r in self.rows[:3])
        if count > 3:
            names += f", +{count - 3} more"
        self._head.update(
            f"[{DIM}]{mark}[/{DIM}] [{color}]{label:<7}[/{color}] "
            f"{count} {noun}  [{DIM}]·[/{DIM}] [{MUTED}]{names}[/{MUTED}]"
        )
        if self._holder is not None:
            self._holder.display = not self.collapsed

    def toggle(self):
        self.collapsed = not self.collapsed

    def on_click(self, event):
        # Only the group's own header line toggles it; clicks on a child row
        # are that row's business.
        if event.widget is self._head or event.widget is self:
            self.toggle()
            event.stop()

    @property
    def copy_text(self) -> str:
        return "\n\n".join(row.copy_text for row in self.rows)
