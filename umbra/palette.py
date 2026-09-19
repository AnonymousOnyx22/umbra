"""Modal pickers: the ctrl+p command palette and the f2 model switcher."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

COMMANDS: list[tuple[str, str]] = [
    ("/help", "list commands"),
    ("/new", "start a new session"),
    ("/resume", "switch to a saved session"),
    ("/sessions", "list saved sessions"),
    ("/model", "switch model"),
    ("/agent", "switch between build and plan"),
    ("/compact", "compact the context now"),
    ("/clear", "clear the transcript"),
    ("/git", "re-detect the git repo"),
    ("/cd", "change the working directory"),
    ("/cwd", "show the working directory"),
    ("/quit", "exit umbra"),
]


class PickerScreen(ModalScreen[str | None]):
    """A filterable list. Dismisses with the chosen value, or None on escape."""

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("down", "cursor_down", "down", show=False),
        Binding("up", "cursor_up", "up", show=False),
    ]

    def __init__(self, title: str, items: list[tuple[str, str]], placeholder: str = "Search..."):
        super().__init__()
        self.title_text = title
        self.items = items
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Label(self.title_text, id="picker-title", markup=False)
            yield Input(placeholder=self.placeholder, id="picker-filter")
            yield OptionList(id="picker-list")

    def on_mount(self) -> None:
        self._refill("")
        self.query_one("#picker-filter", Input).focus()

    def _refill(self, needle: str) -> None:
        listing = self.query_one("#picker-list", OptionList)
        listing.clear_options()
        needle = needle.strip().lower()
        for value, hint in self.items:
            if needle and needle not in value.lower() and needle not in hint.lower():
                continue
            label = f"{value}  —  {hint}" if hint else value
            listing.add_option(Option(label, id=value))
        if listing.option_count:
            listing.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refill(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        listing = self.query_one("#picker-list", OptionList)
        if listing.highlighted is None:
            self.dismiss(None)
            return
        option = listing.get_option_at_index(listing.highlighted)
        self.dismiss(option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cursor_down(self) -> None:
        self.query_one("#picker-list", OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#picker-list", OptionList).action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)


class CommandPalette(PickerScreen):
    def __init__(self) -> None:
        super().__init__("commands", COMMANDS, "Type a command...")


class ModelPicker(PickerScreen):
    def __init__(self, models: list[str], current: str) -> None:
        items = [(name, "current" if name == current else "") for name in models]
        super().__init__("models", items, "Filter models...")
