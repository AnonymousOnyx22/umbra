"""The umbra splash: the ghost, the block-font wordmark, and the hint copy.

The home screen shows a little block ghost above a two-tone wordmark, the way
opencode shows its logo and Claude Code shows its mascot. The font covers the
whole lowercase alphabet, so NAME can be changed without touching anything
else.
"""
from __future__ import annotations

import random

NAME = "umbra"
TAGLINE = "local coding agent"

BLOCK = "█"      # full block
UPPER = "▀"      # upper half block
LOWER = "▄"      # lower half block

# ---------------------------------------------------------------- the ghost

# Umbra: the darkest part of a shadow. Two eyes, a scalloped hem.
GHOST = [
    "  ▄███▄  ",
    " ███████ ",
    " ██ █ ██ ",
    " ███████ ",
    " █▀█▀█▀█ ",
]

GHOST_BODY = "#8b74e8"
GHOST_RIM = "#b9a7ff"
GHOST_HEM = "#6b55c4"

# ----------------------------------------------------------------- the font

# 5-row lowercase block font. '#' = ink, ' ' = paper. Ascenders use row 0.
FONT: dict[str, list[str]] = {
    "a": ["     ", " ####", "#   #", "#   #", " ####"],
    "b": ["#    ", "#### ", "#   #", "#   #", "#### "],
    "c": ["     ", " ####", "#    ", "#    ", " ####"],
    "d": ["    #", " ####", "#   #", "#   #", " ####"],
    "e": ["     ", " ### ", "#####", "#    ", " ### "],
    "f": ["  ## ", " #   ", "#### ", " #   ", " #   "],
    "g": ["     ", " ####", "#   #", " ####", " ### "],
    "h": ["#    ", "#### ", "#   #", "#   #", "#   #"],
    "i": ["  #  ", "     ", "  #  ", "  #  ", "  #  "],
    "j": ["   # ", "     ", "   # ", "#  # ", " ##  "],
    "k": ["#    ", "#  # ", "###  ", "#  # ", "#   #"],
    "l": [" ##  ", "  #  ", "  #  ", "  #  ", "  ## "],
    "m": ["     ", "## ##", "# # #", "# # #", "# # #"],
    "n": ["     ", "#### ", "#   #", "#   #", "#   #"],
    "o": ["     ", " ### ", "#   #", "#   #", " ### "],
    "p": ["#### ", "#   #", "#### ", "#    ", "#    "],
    "q": ["     ", " ####", "#   #", " ####", "    #"],
    "r": ["     ", "# ###", "##   ", "#    ", "#    "],
    "s": ["     ", " ####", "###  ", "   ##", "#### "],
    "t": [" #   ", "#### ", " #   ", " #   ", "  ## "],
    "u": ["     ", "#   #", "#   #", "#   #", " ####"],
    "v": ["     ", "#   #", "#   #", " # # ", "  #  "],
    "w": ["     ", "#   #", "# # #", "# # #", " # # "],
    "x": ["     ", "#   #", " # # ", " # # ", "#   #"],
    "y": ["     ", "#   #", " ####", "    #", " ### "],
    "z": ["     ", "#####", "   # ", "  #  ", "#####"],
    " ": ["     ", "     ", "     ", "     ", "     "],
}

GLYPH_HEIGHT = 5
GLYPH_GAP = 1

# Shadow-to-light violet ramp: the name resolves out of the dark.
RAMP = [
    "#4c3f7a",
    "#5f4f97",
    "#7563b8",
    "#8b74e8",
    "#a693f0",
    "#c4b8f7",
    "#ded6fb",
    "#ffffff",
]


def logo_lines(word: str = NAME) -> list[str]:
    """Render `word` as GLYPH_HEIGHT rows of plain block text."""
    rows = [""] * GLYPH_HEIGHT
    for index, char in enumerate(word.lower()):
        glyph = FONT.get(char)
        if glyph is None:
            continue
        gap = " " * GLYPH_GAP if index else ""
        for row in range(GLYPH_HEIGHT):
            rows[row] += gap + glyph[row].replace("#", BLOCK)
    return rows


def logo_markup(word: str = NAME) -> str:
    """Render `word` as Textual markup, one color per letter along RAMP."""
    rows: list[list[str]] = [[] for _ in range(GLYPH_HEIGHT)]
    letters = word.lower()
    for index, char in enumerate(letters):
        glyph = FONT.get(char)
        if glyph is None:
            continue
        # Short names still walk the full ramp, so they end on white.
        color = RAMP[min(len(RAMP) - 1, index * len(RAMP) // max(1, len(letters)))]
        gap = " " * GLYPH_GAP if index else ""
        for row in range(GLYPH_HEIGHT):
            cell = glyph[row].replace("#", BLOCK)
            rows[row].append(f"{gap}[{color}]{cell}[/{color}]")
    return "\n".join("".join(row) for row in rows)


def ghost_markup() -> str:
    """The mascot: rim-lit dome, violet body, darker hem."""
    colors = [GHOST_RIM, GHOST_BODY, GHOST_BODY, GHOST_BODY, GHOST_HEM]
    return "\n".join(
        f"[{color}]{line}[/{color}]" for color, line in zip(colors, GHOST)
    )


def splash_markup(word: str = NAME) -> str:
    """Ghost centered over the wordmark, as one centered block."""
    ghost_width = max(len(line) for line in GHOST)
    pad = max(0, (logo_width(word) - ghost_width) // 2)
    ghost = "\n".join(
        f"{' ' * pad}[{color}]{line}[/{color}]"
        for color, line in zip(
            [GHOST_RIM, GHOST_BODY, GHOST_BODY, GHOST_BODY, GHOST_HEM], GHOST
        )
    )
    return f"{ghost}\n\n{logo_markup(word)}"


def logo_width(word: str = NAME) -> int:
    return max((len(line) for line in logo_lines(word)), default=0)


SUGGESTIONS = [
    "Fix broken tests",
    "What is the tech stack of this project?",
    "Explain how sessions are persisted",
    "Add a --json flag to the CLI",
    "Where is the entry point?",
    "Refactor the discovery ranking",
    "Write tests for the tool runner",
]

TIPS = [
    "Press f2 to quickly switch between recently used models",
    "Press tab to switch between the build and plan agents",
    "Press ctrl+p to open the command palette",
    "Files are pulled into context automatically - no /add needed",
    "Every edit is shown as a diff and waits for your y/N",
    "umbra runs on local Ollama models, so a session always costs $0.00",
    "Resume yesterday's work with umbra --resume <name>",
    "Nothing leaves this machine - the model runs on your GPU",
]


def random_suggestion() -> str:
    return random.choice(SUGGESTIONS)


def random_tip() -> str:
    return random.choice(TIPS)
