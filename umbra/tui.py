"""umbra - textual TUI for a local Ollama coding assistant.

The shell mirrors opencode: a centered wordmark on the home screen, an
accent-barred composer with the active agent + model under it, key hints on
the right, and a footer that always says which folder you are in. Send a
message and the home screen gives way to the streaming transcript, with the
composer staying put at the bottom.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from . import __version__
from .activity import Activity, ActivityGroup
from .compaction import maybe_compact
from .config import ensure_umbra_dir, load_config, write_setting
from .discovery import discover_for_message
from .gitrepo import current_branch, find_repo_root, git_init
from .logo import NAME, TAGLINE, random_suggestion, random_tip, splash_markup
from .ollama_client import OllamaEngine
from .palette import CommandPalette, ModelPicker
from .sessions import SessionStore
from .tokens import messages_tokens
from .tools import ToolRunner, parse_text_tools

PAL = {
    "read": "#67c01e",
    "grep": "#e8a33d",
    "ls": "#e8a33d",
    "edit": "#e05561",
    "run": "#5aa7e5",
    "tool": "#5b8ff5",
    "assistant": "#a693f0",
    "warn": "#ffb454",
    "info": "#6c7a89",
    "autodiscover": "#67c01e",
}

AGENTS = ("Build", "Plan")

AGENT_NOTES = {
    "Build": "",
    "Plan": (
        " You are in PLAN mode: do not edit files or run commands. Investigate "
        "with read/grep/ls and answer with a concrete plan instead."
    ),
}


class Block(Vertical):
    """Collapsible transcript block with a header line and a body."""

    collapsed = reactive(True)

    def __init__(self, header: str, body: str, *, prefix: str = "trace", expanded: bool = False):
        super().__init__(classes="block")
        self._head = Label("", classes="block-head", markup=True)
        self._body = Static(body, markup=False, classes=f"block-body bb-{prefix}")
        self._body_text = body
        self._header_text = header
        self._prefix = prefix
        self.collapsed = not expanded

    def compose(self):
        yield self._head
        yield self._body

    def on_mount(self):
        self._refresh()

    def watch_collapsed(self, _collapsed: bool):
        self._refresh()

    def _refresh(self):
        if not hasattr(self, "_head"):
            return
        mark = "▾" if not self.collapsed else "▸"
        color = PAL.get(self._prefix, "#9aa3b0")
        self._head.update(f"{mark} [{color}]{self._prefix}[/{color}] {self._header_text}")
        self._body.display = not self.collapsed

    def on_click(self, event):
        # Right-click copies the block instead of toggling it.
        if getattr(event, "button", 1) == 3:
            self.app.copy_block(self)
            event.stop()
            return
        self.collapsed = not self.collapsed

    def on_mouse_down(self, event):
        if getattr(event, "button", 1) == 3:
            self.app.copy_block(self)
            event.stop()

    @property
    def copy_text(self) -> str:
        return f"{self._prefix}  {self._header_text}\n{self._body_text}"


class UserMsg(Static):
    def __init__(self, text: str):
        super().__init__(text, markup=False, classes="user-msg")


class StreamText(Static):
    def __init__(self, prefix: str = "assistant"):
        super().__init__("", markup=False, classes=f"stream bb-{prefix}")
        self.text = ""

    def add(self, chunk: str):
        self.text += chunk
        self.update(self.text)


class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, question: str, yes_label: str = "Yes", no_label: str = "No"):
        super().__init__()
        self.question = question
        self.yes_label = yes_label
        self.no_label = no_label

    def compose(self) -> ComposeResult:
        with Horizontal(id="confirm-wrap"):
            with Vertical(id="confirm-box"):
                yield Label(self.question, markup=False)
                with Horizontal(id="confirm-row"):
                    yield Button(self.yes_label, variant="primary", id="yes")
                    yield Button(self.no_label, id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


_NATIVE_CALLS_RE = re.compile(r"<read|grep|ls|edit|run", re.I)

# Categories worth folding into a group when they repeat. Edits and commands
# never fold - you always want those on their own line.
_GROUPABLE = {"read", "grep", "ls", "context"}

_BODY_LIMIT = 4000


def _clip_body(text: str) -> str:
    if len(text) <= _BODY_LIMIT:
        return text
    return text[:_BODY_LIMIT] + f"\n... ({len(text):,} chars total)"


def _count(text: str, noun: str) -> str:
    if text.startswith("ERROR"):
        return "error"
    return f"{len(text.splitlines()):,} {noun}"


def _diff_markup(diff: str) -> str:
    """Color a unified diff for the expanded body of an edit row."""
    out = []
    for line in _clip_body(diff).splitlines():
        safe = line.replace("[", "\\[")
        if line.startswith("+++") or line.startswith("---"):
            out.append(f"[#6c7a89]{safe}[/#6c7a89]")
        elif line.startswith("@@"):
            out.append(f"[#a693f0]{safe}[/#a693f0]")
        elif line.startswith("+"):
            out.append(f"[#67c01e]{safe}[/#67c01e]")
        elif line.startswith("-"):
            out.append(f"[#e05561]{safe}[/#e05561]")
        else:
            out.append(f"[#9aa3b0]{safe}[/#9aa3b0]")
    return "\n".join(out)


class Umbra(App):
    TITLE = NAME
    CSS = """
    Screen { background: #0b0b0d; }

    #main { height: 1fr; padding: 0 2; }
    .spacer { height: 1fr; }

    #logo { width: 100%; content-align: center middle; height: auto; padding: 0 0 1 0; }
    #home-tag {
        width: 100%; content-align: center middle; height: auto;
        padding: 0 0 1 0;
    }
    #home-sub {
        width: 100%; content-align: center middle; height: auto;
        color: #6c7a89; padding: 0 0 2 0;
    }

    #transcript-scroll { width: 1fr; height: 1fr; padding: 1 0; }

    #composer {
        height: auto; background: #17171b; border-left: thick #8b74e8;
        padding: 0 1;
    }
    #prompt {
        border: none; background: transparent; padding: 0 1; height: 1;
    }
    #prompt-meta { height: 1; padding: 0 1; }

    #hints { height: 1; padding: 0 1; }
    #hints-left { width: 1fr; color: #6c7a89; }
    #hints-right { width: auto; text-align: right; }
    #tip { height: auto; width: 100%; content-align: center middle;
           color: #6c7a89; padding: 1 0 0 0; }

    #footer { dock: bottom; height: 1; background: #0b0b0d; padding: 0 2; }
    #footer-left { width: 1fr; color: #6c7a89; }
    #footer-right { width: auto; color: #6c7a89; text-align: right; }

    UserMsg { color: $text; background: #17171b; border-left: thick #3f4c5f;
              padding: 0 1; margin: 0 0 1 0; }
    .stream { margin: 0 0 1 0; }

    .activity { height: auto; }
    .activity-group { height: auto; }
    .act-head { width: 100%; height: auto; }
    .act-head:hover { background: #17171b; }
    .act-body {
        height: auto; padding: 0 1; margin: 0 0 1 2;
        border-left: solid #2a2a33; color: #9aa3b0;
    }
    .act-children { height: auto; padding: 0 0 0 2; }

    .block { margin: 0 0 1 0; }
    .block-head { color: $accent; }
    .block-body { padding: 0 1; }
    .bb-read { color: #67c01e; }
    .bb-grep { color: #e8a33d; }
    .bb-ls { color: #e8a33d; }
    .bb-edit { color: #e05561; }
    .bb-run { color: #5aa7e5; }
    .bb-assistant { color: #c8bfec; }
    .bb-autodiscover { color: #67c01e; }
    .bb-warn { color: #ffb454; }
    .bb-info { color: #6c7a89; }

    #confirm-wrap { width: 100%; height: 100%; align: center middle; }
    #confirm-box { width: 64; height: auto; border: round $accent; padding: 1 2;
                   background: #17171b; }
    #confirm-box Label { height: auto; }
    #confirm-row { height: auto; align-horizontal: right; padding-top: 1; }
    #confirm-row Button { min-width: 10; height: 3; margin-left: 1; }

    PickerScreen { align: center middle; background: #0b0b0daa; }
    #picker-box { width: 72; height: auto; max-height: 24; background: #17171b;
                  border-left: thick #8b74e8; padding: 0 1; }
    #picker-title { color: #6c7a89; height: 1; padding: 0 1; }
    #picker-filter { border: none; background: transparent; padding: 0 1; height: 1; }
    #picker-list { height: auto; max-height: 18; background: transparent;
                   border: none; padding: 0 1; }
    """

    BINDINGS = [
        Binding("ctrl+p", "commands", "commands", priority=True),
        Binding("tab", "cycle_agent", "agents", priority=True),
        Binding("f2", "pick_model", "model", priority=True),
        Binding("ctrl+n", "new_session", "new session"),
        Binding("escape", "interrupt", "interrupt", show=False),
        # Click-out recovery and copying. ctrl+c is already bound by Textual to
        # copy the drag-selection; these cover the rest.
        Binding("ctrl+shift+c", "copy_selection", "copy", show=False),
        Binding("ctrl+b", "focus_input", "prompt", show=False),
        Binding("f12", "toggle_mouse", "mouse", show=False),
        Binding("ctrl+e", "toggle_all", "expand all", priority=True, show=False),
    ]

    def __init__(self, cfg, model=None, host=None, resume=None, session_name=None,
                 yes=False, yolo=False, cwd: Path | None = None):
        super().__init__()
        self.cfg = cfg
        self.model = model or cfg.model
        self.host = host or cfg.host
        # yolo = total permission: no confirmations, no git gate, whole machine.
        self.yolo = yolo or bool(cfg.auto_approve)
        self.yes = yes or self.yolo
        self._undo: list[tuple[str, str]] = []
        self._flash_text = ""
        self._mouse_off = False
        self.workdir = (cwd or Path.cwd()).resolve()
        self.store = SessionStore()
        self.engine = OllamaEngine(self.host, self.model)
        self.root = find_repo_root(self.workdir)
        self.branch = current_branch(self.root)
        self.agent = AGENTS[0]
        self._models: list[str] = []

        name = resume or session_name or cfg.default_session
        existing = self.store.load(name)
        if existing is not None:
            existing.cwd = str(self.workdir)
            existing.model = self.model
            self.session = existing
        else:
            self.session = self.store.new(name, str(self.workdir), self.model)
            self.session.messages.append(self._fresh_system_prompt())

        self._turn_tokens = 0
        self._thinking = False

    # ------------------------------------------------------------------ UI

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield Static("", classes="spacer", id="spacer-top")
            yield Static(splash_markup(), id="logo", markup=True)
            yield Static(
                f"[#6c7a89]{TAGLINE}[/#6c7a89]", id="home-tag", markup=True)
            yield Static("", id="home-sub", markup=True)
            yield VerticalScroll(id="transcript-scroll")
            with Vertical(id="composer"):
                yield Input(
                    placeholder=f'Ask anything… "{random_suggestion()}"',
                    id="prompt",
                )
                yield Static("", id="prompt-meta", markup=True)
            with Horizontal(id="hints"):
                yield Static("", id="hints-left", markup=True)
                yield Static("", id="hints-right", markup=True)
            yield Static("", id="tip", markup=True)
            yield Static("", classes="spacer", id="spacer-bottom")
        with Horizontal(id="footer"):
            yield Static("", id="footer-left", markup=True)
            yield Static("", id="footer-right", markup=True)

    def on_mount(self):
        self.transcript = self.query_one("#transcript-scroll", VerticalScroll)
        self.prompt = self.query_one("#prompt", Input)
        # Cached because query_one() searches the *active* screen, and chrome
        # gets repainted while a modal (confirm / palette) is on top.
        self._w = {
            wid: self.query_one(f"#{wid}", Static)
            for wid in ("spacer-top", "spacer-bottom", "logo", "home-tag",
                        "home-sub", "tip", "prompt-meta",
                        "hints-left", "hints-right",
                        "footer-left", "footer-right")
        }
        self.prompt.focus()

        self._home = True
        self._show_history()
        self._render_home(self._home)
        self._render_chrome()
        self.run_worker(self._load_models(), name="models")

        if self.root is None:
            self.run_worker(self._offer_git_init(), name="git-prompt")

    # ---------------------------------------------------------- home/chat

    def _render_home(self, home: bool):
        """Home screen = centered wordmark; chat = transcript above the composer."""
        self._home = home
        for wid in ("spacer-top", "spacer-bottom", "logo", "home-tag",
                    "home-sub", "tip"):
            self._w[wid].display = home
        self.transcript.display = not home
        if home:
            self._w["tip"].update(
                f"[#ffb454]• Tip[/#ffb454]  [#6c7a89]{random_tip()}[/#6c7a89]"
            )
            folder = self.workdir.name or str(self.workdir)
            parent = str(self.workdir.parent).rstrip("\\/")
            where = (f"[#6c7a89]{parent}[/#6c7a89]"
                     f"[b #d4d4dc]{os.sep}{folder}[/b #d4d4dc]")
            if self.branch:
                where += f"  [#6c7a89]·[/#6c7a89]  [#67c01e]{self.branch}[/#67c01e]"
            else:
                where += "  [#6c7a89]·[/#6c7a89]  [#ffb454]no git repo[/#ffb454]"
            self._w["home-sub"].update(where)

    def _render_chrome(self):
        """The composer meta line, the key hints, and the folder footer."""
        provider = self.host.replace("http://", "").replace("https://", "")
        badge = ("[b #e05561]YOLO[/b #e05561] [#4a4a52]·[/#4a4a52] "
                 if self.yolo else "")
        self._w["prompt-meta"].update(
            badge +
            f"[#a693f0]{self.agent}[/#a693f0] [#4a4a52]·[/#4a4a52] "
            f"[#d4d4dc]{self.model}[/#d4d4dc] "
            f"[#6c7a89]ollama[/#6c7a89] [#4a4a52]{provider}[/#4a4a52]"
        )

        left = ""
        if getattr(self, "_flash_text", ""):
            left = f"[#a693f0]{self._flash_text}[/#a693f0]"
        elif not self._home:
            used = messages_tokens(self.session.messages) + self._turn_tokens
            window = self.cfg.context_window
            pct = int(100 * used / max(1, window))
            color = "#ffb454" if pct > 60 else "#67c01e"
            left = (
                f"[#6c7a89]{self.session.name}[/#6c7a89]  "
                f"[{color}]{pct}%[/{color}][#6c7a89] ctx[/#6c7a89]"
            )
        if getattr(self, "_mouse_off", False):
            hints = (
                "[b #ffb454]f12[/b #ffb454] [#6c7a89]terminal mouse - "
                "drag to select, right-click to copy[/#6c7a89]"
            )
        else:
            hints = (
                "[b #d4d4dc]tab[/b #d4d4dc] [#6c7a89]agents[/#6c7a89]   "
                "[b #d4d4dc]ctrl+p[/b #d4d4dc] [#6c7a89]commands[/#6c7a89]   "
                "[b #d4d4dc]ctrl+c[/b #d4d4dc] [#6c7a89]copy[/#6c7a89]"
            )
        self._w["hints-left"].update(left)
        self._w["hints-right"].update(hints)

        where = f"{self.workdir}"
        if self.branch:
            where += f"  ·  {self.branch}"
        self._w["footer-left"].update(f"[#6c7a89]{where}[/#6c7a89]")
        self._w["footer-right"].update(f"[#6c7a89]umbra {__version__}[/#6c7a89]")

    async def _load_models(self):
        self._models = await asyncio.to_thread(self.engine.list_models)

    def _show_history(self):
        shown = False
        for msg in self.session.messages:
            content = str(msg.get("content", ""))
            if msg.get("role") == "user" and content.startswith("Earlier conversation"):
                self._add_block("Compacted summary", content[:400], prefix="info")
                shown = True
            elif msg.get("role") == "user" and not content.startswith("### "):
                self.transcript.mount(UserMsg(content))
                shown = True
        if shown:
            self._render_home(False)
            self._scroll_end()

    def _add_block(self, header: str, body: str, *, prefix: str = "tool",
                   expanded: bool = False) -> Block:
        block = Block(header, body, prefix=prefix, expanded=expanded)
        self.transcript.mount(block)
        return block

    def _activity(self, prefix: str, title: str, body: str = "", *,
                  summary: str = "", running: bool = False,
                  expanded: bool = False, diff: bool = False) -> Activity:
        """Mount one action row in the feed, optionally live.

        Consecutive rows of the same category fold into a group, so twelve
        reads in a row read as one line until you open them.
        """
        if diff:
            body = _diff_markup(body)
        row = Activity(prefix, title, body, summary=summary, running=running,
                       expanded=expanded, body_markup=diff)

        last = self.transcript.children[-1] if self.transcript.children else None
        if isinstance(last, ActivityGroup) and last.prefix == prefix:
            last.add(row)
        elif (isinstance(last, Activity) and last.prefix == prefix
              and not last.running and prefix in _GROUPABLE):
            # Second row of a kind: retire the standalone row into a new group.
            previous = Activity(last.prefix, last.title_text, last._body_text,
                                summary=last.summary)
            previous.elapsed = last.elapsed
            group = ActivityGroup(prefix, [previous, row])
            self.transcript.mount(group, after=last)
            last.remove()
        else:
            self.transcript.mount(row)
        self._scroll_end()
        return row

    def action_toggle_all(self):
        """Expand everything, or fold it all back up."""
        rows = list(self.transcript.query(Activity)) + \
            list(self.transcript.query(ActivityGroup)) + \
            list(self.transcript.query(Block))
        if not rows:
            return
        target = any(getattr(r, "collapsed", True) for r in rows)
        for row in rows:
            row.collapsed = not target
        self._flash("expanded everything" if target else "collapsed everything")

    def _append_user(self, text: str):
        self.transcript.mount(UserMsg(text))
        self._scroll_end()

    def _scroll_end(self):
        self.transcript.scroll_end(animate=False)

    # -------------------------------------------------------------- actions

    def action_focus_input(self):
        self.prompt.focus()

    def on_click(self, event) -> None:
        """Clicking anywhere in the transcript puts the cursor back in the box.

        Without this, clicking the transcript leaves nowhere to type.
        """
        if len(self.screen_stack) > 1:      # a modal owns the focus
            return
        if getattr(event, "button", 1) == 3:
            return
        if self.screen.get_selected_text():  # don't fight a drag-selection
            return
        self.prompt.focus()

    # ---------------------------------------------------------- copy / mouse

    def copy_block(self, block) -> None:
        """Right-click on any feed row copies its header + body."""
        label = getattr(block, "prefix", None) or getattr(block, "_prefix", "block")
        self._copy(block.copy_text, f"{label} row")

    def _copy(self, text: str, what: str) -> None:
        if not text:
            self._flash("nothing to copy")
            return
        try:
            self.copy_to_clipboard(text)
        except Exception as exc:  # noqa: BLE001
            self._flash(f"copy failed: {exc}")
            return
        self._flash(f"copied {what} ({len(text):,} chars)")

    def action_copy_selection(self) -> None:
        """Copy the drag-selection, else the last assistant message."""
        selected = self.screen.get_selected_text()
        if selected:
            self._copy(selected, "selection")
            return
        for widget in reversed(list(self.transcript.children)):
            if isinstance(widget, StreamText) and widget.text.strip():
                self._copy(widget.text, "last reply")
                return
        self._flash("nothing selected")

    def action_toggle_mouse(self) -> None:
        """Hand the mouse back to the terminal, so its own selection works.

        With mouse reporting off you can drag-select and right-click-copy the
        way you would in any console window; f12 again returns it to umbra.
        """
        driver = getattr(self, "_driver", None)
        if driver is None:
            return
        self._mouse_off = not getattr(self, "_mouse_off", False)
        try:
            if self._mouse_off:
                driver._disable_mouse_support()
            else:
                driver._enable_mouse_support()
        except Exception as exc:  # noqa: BLE001
            self._mouse_off = not self._mouse_off   # it never took effect
            self._flash(f"mouse toggle failed: {exc}")
            return
        self._render_chrome()
        self._flash("terminal mouse - drag to select, right-click to copy (f12 back)"
                    if self._mouse_off else "umbra mouse - click to expand traces")

    def _flash(self, message: str) -> None:
        """One-line transient status in the hint row."""
        self._flash_text = message
        self._render_chrome()
        self.set_timer(4, self._clear_flash)

    def _clear_flash(self) -> None:
        self._flash_text = ""
        self._render_chrome()

    def action_new_session(self):
        self.run_worker(self._do_new_session(auto=True))

    def action_cycle_agent(self):
        self.agent = AGENTS[(AGENTS.index(self.agent) + 1) % len(AGENTS)]
        self._render_chrome()

    def action_commands(self):
        self.run_worker(self._pick_command(), name="palette")

    def action_pick_model(self):
        self.run_worker(self._pick_model(), name="modelpick")

    def action_interrupt(self):
        """Cancel the running turn, or - if nothing is running - take the box back."""
        running = [w for w in self.workers if w.name == "turn"]
        for worker in running:
            worker.cancel()
        if not running:
            self.prompt.focus()

    async def _pick_command(self):
        choice = await self.push_screen(CommandPalette(), wait_for_dismiss=True)
        if choice:
            self._do_command(choice)

    async def _pick_model(self):
        if not self._models:
            self._models = await asyncio.to_thread(self.engine.list_models)
        if not self._models:
            self._notice("Models", f"no models reported by {self.host}", prefix="warn")
            return
        choice = await self.push_screen(
            ModelPicker(self._models, self.model), wait_for_dismiss=True)
        if choice:
            self._set_model(choice)

    def _set_model(self, name: str):
        self.model = name
        self.engine.model = name
        self.session.model = name
        self.store.save(self.session)
        self._render_chrome()

    def _notice(self, header: str, body: str, *, prefix: str = "info"):
        """Blocks only exist in the transcript, so a notice leaves the home screen."""
        if self._home:
            self._render_home(False)
        self._add_block(header, body, prefix=prefix, expanded=True)
        self._render_chrome()
        self._scroll_end()

    # --------------------------------------------------------------- input

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "prompt":
            return
        text = event.value.strip()
        self.prompt.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._do_command(text)
        else:
            self.run_worker(self._handle_user(text), name="turn", exclusive=True)

    def _do_command(self, text: str):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in ("/help", "/?"):
            self._notice("Commands", (
                "/help, /clear, /sessions, /new <name>, /resume <name>,\n"
                "/model [name], /agent, /compact, /git, /cd <path>, /cwd,\n"
                "/yolo [on|off], /undo, /audit, /pull <model>, /quit\n"
                "keys: tab agents  ctrl+p commands  f2 model  "
                "ctrl+n new session  esc interrupt"
            ))
        elif cmd == "/clear":
            kept = [m for m in self.session.messages if m.get("role") == "system"][:1]
            self.session.messages = kept
            self.transcript.remove_children()
            self.store.save(self.session)
            self._render_home(True)
            self._render_chrome()
        elif cmd == "/sessions":
            names = self.store.names()
            self._notice("Sessions", "\n".join(names) or "(none)")
        elif cmd == "/new":
            name = arg.strip() or "default"
            self.run_worker(self._do_new_session(name=name))
        elif cmd == "/resume":
            self.run_worker(self._do_resume(arg.strip()))
        elif cmd == "/model":
            if arg.strip():
                self._set_model(arg.strip())
                self._notice("Model", f"switched to {self.model}")
            else:
                self.action_pick_model()
        elif cmd == "/agent":
            self.action_cycle_agent()
            self._notice("Agent", f"{self.agent} mode")
        elif cmd == "/compact":
            self.session.messages, did = maybe_compact(
                self.session.messages, self.cfg.context_window, ratio=0.5)
            self._notice("Compact", "done manually" if did else "nothing to compact")
            self.store.save(self.session)
        elif cmd == "/git":
            self.root = find_repo_root(self.workdir)
            self.branch = current_branch(self.root)
            self._notice("Git", str(self.root) if self.root else "no repo found")
        elif cmd == "/pull":
            self.run_worker(self._pull_model(arg.strip()), name="pull")
        elif cmd == "/yolo":
            self._set_yolo(arg.strip())
        elif cmd == "/undo":
            self._undo_last()
        elif cmd == "/audit":
            self._show_audit()
        elif cmd == "/cd":
            self._change_dir(arg.strip())
        elif cmd == "/cwd":
            self._notice("Folder", f"{self.workdir}\nrepo: {self.root or '(none)'}"
                                   f"\nbranch: {self.branch or '(none)'}")
        elif cmd in ("/quit", "/exit"):
            self.exit()
        else:
            self._notice("Unknown", f"no such command: {cmd} — /help", prefix="warn")

    async def _pull_model(self, name: str):
        """`/pull <model>` - bring any Ollama model down without leaving umbra.

        Works for anything Ollama can fetch, including models you built
        yourself from a Modelfile or imported from a GGUF.
        """
        if not name:
            self._notice("Pull", "usage: /pull <model>   e.g. /pull qwen2.5-coder:14b",
                         prefix="warn")
            return
        if self._home:
            self._render_home(False)
        row = self._activity("info", f"ollama pull {name}", running=True)
        try:
            proc = await asyncio.to_thread(
                subprocess.run, ["ollama", "pull", name],
                capture_output=True, text=True,
            )
        except FileNotFoundError:
            row.finish("ollama not found", "Install Ollama and make sure "
                                           "`ollama` is on your PATH.")
            return
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0:
            row.finish("pulled", output or f"{name} is ready")
            self._models = await asyncio.to_thread(self.engine.list_models)
            self._flash(f"{name} pulled - press f2 to switch to it")
        else:
            row.finish(f"failed (exit {proc.returncode})", output)

    # ------------------------------------------------- total permission mode

    def _set_yolo(self, arg: str):
        """Toggle (and persist) unattended mode: no prompts, no repo gate."""
        want = (not self.yolo) if not arg else arg.lower() in ("on", "true", "1", "yes")
        self.yolo = want
        self.yes = want
        write_setting("auto_approve", want)
        self._render_chrome()
        if want:
            self._notice("YOLO", (
                "ON - edits and shell commands run with no confirmation,\n"
                "anywhere on this machine, git repo or not.\n"
                "Overwritten files are backed up; /undo restores the last one,\n"
                "/audit shows what has been run. esc interrupts a turn."
            ), prefix="warn")
        else:
            self._notice("YOLO", "OFF - edits and commands ask again.")

    def _audit_path(self) -> Path:
        return ensure_umbra_dir() / "audit.log"

    def _audit(self, kind: str, detail: str):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self._audit_path(), "a", encoding="utf-8") as fh:
                fh.write(f"{stamp}  {kind:<5} {detail}\n")
        except OSError:
            pass

    def _show_audit(self, count: int = 25):
        try:
            lines = self._audit_path().read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        body = "\n".join(lines[-count:]) or "(nothing logged yet)"
        self._notice(f"Audit  {self._audit_path()}", body)

    def _undo_last(self):
        """Restore the most recent file the model overwrote."""
        if not self._undo:
            self._notice("Undo", "nothing to undo in this session", prefix="warn")
            return
        target, backup = self._undo.pop()
        try:
            import shutil

            shutil.copy2(backup, target)
        except OSError as exc:
            self._notice("Undo", f"could not restore {target}: {exc}", prefix="warn")
            return
        self._audit("undo", f"{target} <- {backup}")
        self._notice("Undo", f"restored {target}\nfrom {backup}")

    def _change_dir(self, raw: str):
        """Re-root the session, so a Start Menu launch can hop into a project."""
        if not raw:
            self._notice("Folder", str(self.workdir))
            return
        target = Path(raw.strip("\"'")).expanduser()
        if not target.is_absolute():
            target = self.workdir / target
        try:
            target = target.resolve(strict=True)
        except OSError:
            self._notice("cd", f"no such directory: {raw}", prefix="warn")
            return
        if not target.is_dir():
            self._notice("cd", f"not a directory: {target}", prefix="warn")
            return
        self.workdir = target
        self.root = find_repo_root(self.workdir)
        self.branch = current_branch(self.root)
        self.session.cwd = str(self.workdir)
        self.session.messages.append({
            "role": "system",
            "content": f"Working directory changed to {self.workdir}. "
                       "Earlier file context may be stale.",
        })
        self.store.save(self.session)
        self._notice("cd", f"{self.workdir}\nrepo: {self.root or '(none)'}"
                           f"\nbranch: {self.branch or '(none)'}")

    async def _do_new_session(self, name: str | None = None, auto: bool = False):
        if auto or not name:
            name = name or f"{self.session.name}-{int(time.time())}"
        self.session = self.store.new(name, str(self.workdir), self.model)
        self.session.messages.append(self._fresh_system_prompt())
        self.store.save(self.session)
        self.transcript.remove_children()
        self._render_home(True)
        self._render_chrome()

    async def _do_resume(self, name: str):
        existing = self.store.load(name) if name else None
        if existing is None:
            self._notice("Resume", f"no session named {name!r}", prefix="warn")
            return
        existing.cwd = str(self.workdir)
        self.session = existing
        self.transcript.remove_children()
        self._render_home(True)
        self._show_history()
        self._render_chrome()

    def _fresh_system_prompt(self) -> dict:
        return {
            "role": "system",
            "content": (
                "You are umbra, a terminal coding assistant running on local "
                f"Ollama models. Working directory: {self.workdir}. "
                "You can read files, grep the repo, list directories, edit "
                "files, and run shell commands. To use a tool, emit an XML "
                "tag like <read path='file.py'/> <grep pattern='...' "
                "path='...'/> <ls path='.'/> <edit path='file.py'>NEW "
                "CONTENT</edit> or <run>command</run>, OR use native function "
                "calls if you support them. Prefer reading before editing. "
                "Each edit replaces the file's entire contents."
            ),
        }

    # -------------------------------------------------------------- turns

    async def _offer_git_init(self):
        ok = await self.confirm(
            f"No git repo in {self.workdir}.\nRun `git init` so file edits stay tracked?"
        )
        if ok:
            await self._git_init_now()

    async def _git_init_now(self):
        try:
            out, _err = await asyncio.to_thread(git_init, self.workdir)
            self.root = find_repo_root(self.workdir)
            self.branch = current_branch(self.root)
            self._notice("Git", (out or "").strip() or f"initialized {self.workdir}")
        except Exception as exc:  # noqa: BLE001
            self._notice("Git", f"git init failed: {exc}", prefix="warn")

    async def confirm(self, question: str, yes_label="Yes", no_label="No") -> bool:
        screen = ConfirmScreen(question, yes_label, no_label)
        result = await self.push_screen(screen, wait_for_dismiss=True)
        return bool(result)

    async def _handle_user(self, text: str):
        try:
            self._thinking = True
            if self._home:
                self._render_home(False)
            self._append_user(text)
            self.session.messages.append({"role": "user", "content": text})

            files = discover_for_message(
                self.workdir, self.root, text,
                self.cfg.discovery_top_n, self.cfg.discovery_max_file_chars,
            )
            if files:
                for f in files:
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    rel = f.relative_to(self.root) if self.root else f
                    short = content[: self.cfg.discovery_max_file_chars]
                    self._activity("context", str(rel), _clip_body(short),
                                   summary=_count(content, "lines"))
                    self.session.messages.append({
                        "role": "system",
                        "content": f"### Relevant file: {rel}\n```\n{short}\n```",
                    })
                self._scroll_end()

            self.store.save(self.session)
            await self._assistant_loop()
        except asyncio.CancelledError:
            self._add_block("Interrupted", "turn cancelled", prefix="warn")
            raise
        except Exception as exc:  # noqa: BLE001
            self._add_block("Error", str(exc), prefix="warn")
        finally:
            self._thinking = False
            self._render_chrome()
            self.prompt.focus()

    def _chunk_cb(self, widget: StreamText):
        app_thread = threading.get_ident()

        def cb(text: str):
            if threading.get_ident() == app_thread:
                widget.add(text)
            else:
                self.call_from_thread(widget.add, text)
        return cb

    def _agent_messages(self) -> list[dict]:
        """The session messages, with the active agent's rider on the system prompt."""
        note = AGENT_NOTES.get(self.agent, "")
        if not note:
            return self.session.messages
        messages = list(self.session.messages)
        for index, msg in enumerate(messages):
            if msg.get("role") == "system":
                messages[index] = {**msg, "content": str(msg.get("content", "")) + note}
                break
        return messages

    async def _assistant_loop(self):
        for _ in range(self.cfg.max_tool_iterations):
            self._render_chrome()
            stream = StreamText("assistant")
            self.transcript.mount(stream)
            self._scroll_end()

            try:
                native, content = await self.engine.chat(
                    self._agent_messages(), self._chunk_cb(stream),
                )
            except Exception as exc:  # noqa: BLE001
                stream.add(f"\n\n[error] {exc}")
                return

            if not native:
                native = parse_text_tools(content)

            if not native:
                self.session.messages.append({"role": "assistant", "content": stream.text})
                break

            self._add_block("Tool", f"{len(native)} call(s) — running...", prefix="tool")
            assistant_msg = {"role": "assistant", "content": stream.text or content}
            if self._engine_used_native(native, stream):
                assistant_msg["tool_calls"] = self._native_form(native)
            self.session.messages.append(assistant_msg)

            for call in native:
                result, ok = await self._execute_call(call)
                if result is None:  # user rejected -> stop the turn
                    self._add_block("Cancelled", "edit/command declined by user",
                                    prefix="warn")
                    return
                self.session.messages.append({
                    "role": "tool",
                    "name": call["name"],
                    "content": result,
                })
            self._scroll_end()

        self.session.messages, did_compact = maybe_compact(
            self.session.messages, self.cfg.context_window, self.cfg.compact_ratio)
        if did_compact:
            self._add_block("Compact", "older turns summarized to free context",
                            prefix="info")
        self.store.save(self.session)
        self._render_chrome()

    def _engine_used_native(self, calls, stream) -> bool:
        return any("arguments" in (c.get("arguments") or {}) for c in calls)

    def _native_form(self, calls) -> list[dict]:
        return [
            {"function": {"name": c["name"], "arguments": c.get("arguments", {})}}
            for c in calls
        ]

    async def _execute_call(self, call) -> tuple[str | None, bool]:
        runner = ToolRunner(
            self.root, self.workdir,
            require_git=not self.yolo,
            timeout=self.cfg.command_timeout,
        )
        name = call["name"]
        args = call.get("arguments", {}) or {}

        if name == "read":
            path = str(args.get("path", ""))
            row = self._activity("read", path, running=True)
            result = await asyncio.to_thread(runner.read, path)
            row.finish(_count(result, "lines"), _clip_body(result))
            return result, True

        if name == "ls":
            path = str(args.get("path", "."))
            row = self._activity("ls", path, running=True)
            result = await asyncio.to_thread(runner.ls, path)
            row.finish(_count(result, "entries"), _clip_body(result))
            return result, True

        if name == "grep":
            pattern = str(args.get("pattern", ""))
            where = str(args.get("path", "")) or "."
            row = self._activity("grep", f"{pattern}  [in {where}]", running=True)
            result = await asyncio.to_thread(runner.grep, pattern, str(args.get("path", "")))
            hits = 0 if result.startswith("no matches") else len(result.splitlines())
            row.finish(f"{hits} matches", _clip_body(result))
            return result, True

        if name in ("edit", "run") and self.agent == "Plan":
            self._activity("warn", f"{name} blocked",
                           body="Plan mode is read-only - no edits or commands.",
                           summary="plan mode")
            return f"BLOCKED: plan mode is read-only, {name} was not executed", False

        if name == "edit":
            if self.root is None and not self.yes:
                ok = await self.confirm("No git repo. Run `git init` so edits are tracked?")
                if ok:
                    await self._git_init_now()
                else:
                    return None, False
            pending = await asyncio.to_thread(
                runner.edit, str(args.get("path", "")), str(args.get("content", "")))
            if pending.get("status") == "unchanged":
                self._activity("edit", str(args.get("path", "")),
                               summary="no change")
                return "no change - file already matches", False
            diff = pending["diff"] or "(new file)"
            added = sum(1 for ln in diff.splitlines()
                        if ln.startswith("+") and not ln.startswith("+++"))
            removed = sum(1 for ln in diff.splitlines()
                          if ln.startswith("-") and not ln.startswith("---"))
            row = self._activity(
                "edit", str(args.get("path", "")),
                body=diff, summary=f"+{added} -{removed}",
                expanded=True, diff=True,
            )
            row.elapsed = None
            if not self.yes:
                ok = await self.confirm("Apply this edit?")
                if not ok:
                    return None, False
            backup = await asyncio.to_thread(
                runner.apply_edit, args["path"], args["content"])
            target = pending.get("path", args["path"])
            if backup:
                self._undo.append((target, backup))
            self._audit("edit", f"{target}  (backup: {backup or 'new file'})")
            return f"OK - applied edit to {args['path']}", False

        if name == "run":
            if self.root is None and not self.yes:
                ok = await self.confirm("No git repo. Run `git init` so commands are sandboxed?")
                if ok:
                    await self._git_init_now()
                else:
                    return None, False
            command = str(args.get("command", ""))
            if not self.yes:
                ok = await self.confirm(f"Run command?\n$ {command}")
                if not ok:
                    self._activity("run", command, summary="declined")
                    return None, False
            self._audit("run", f"{command}   [cwd {self.workdir}]")
            row = self._activity("run", command, running=True)
            result = await asyncio.to_thread(runner.run, command)
            exit_code = result.split("]", 1)[0].lstrip("[") if result.startswith("[") else ""
            row.finish(exit_code or "done", _clip_body(result))
            return result, True

        return f"ERROR: unknown tool {name}", False

    def on_unmount(self):
        if getattr(self, "session", None) is not None:
            try:
                self.store.save(self.session)
            except Exception:  # noqa: BLE001
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="umbra",
        description="Local Ollama-backed terminal coding assistant.",
    )
    parser.add_argument("--model", default=None, help="Ollama model name")
    parser.add_argument("--host", default=None, help="Ollama server URL")
    parser.add_argument("--resume", metavar="NAME", help="resume a session")
    parser.add_argument("--session", metavar="NAME", help="use a named session")
    parser.add_argument("--yes", action="store_true",
                        help="auto-accept edits and shell commands")
    parser.add_argument("--yolo", action="store_true",
                        help="total permission: no confirmations, no git gate, "
                             "anywhere on the machine")
    parser.add_argument("--cwd", default=None, help="working directory")
    parser.add_argument("--version", action="version", version=f"umbra {__version__}")
    args = parser.parse_args(argv)

    cfg = load_config()
    app = Umbra(
        cfg,
        model=args.model,
        host=args.host,
        resume=args.resume,
        session_name=args.session,
        yes=args.yes,
        yolo=args.yolo,
        cwd=Path(args.cwd) if args.cwd else None,
    )
    app.run()


if __name__ == "__main__":
    main()
