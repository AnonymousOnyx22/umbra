# umbra

**[anonymousonyx22.github.io/umbra](https://anonymousonyx22.github.io/umbra/)**

A terminal coding agent that runs **entirely on your own machine**. Bring any
Ollama model — including ones you built yourself — and watch every move it
makes. No cloud APIs, no keys, no account; a session costs $0.00.

```
                  ▄███▄
                 ███████
                 ██ █ ██
                 ███████
                 █▀█▀█▀█

       █
   █   █ ██ ██ ████  █ ███  ████
   █   █ █ █ █ █   █ ██    █   █
   █   █ █ █ █ █   █ █     █   █
    ████ █ █ █ ████  █      ████

       local coding agent
```

## Features

- **Ghost home screen**: the block wordmark, a rotating suggestion in the
  composer, and a tip line. The composer carries a violet accent bar with the
  active agent, model and Ollama host under it; key hints sit on the right; the
  footer always shows the folder you're in (plus the git branch) on the left and
  the version on the right. Send a message and the home screen gives way to the
  streaming transcript, with the session name and context usage moving into the
  hint row.
- **A thinking animation** between sending and the first token — spinner, the
  ghost's eyes blinking, and a running clock, so a slow local model never looks
  like a hung one.
- **The agent can move itself.** Ask it to "go to ~/code/api" and it calls the
  `cd` tool; the working directory, git repo, branch and the folder in the
  bottom-left footer all follow.
- **Watch it work.** Every read, search, edit and command is one categorized,
  timed row in the activity feed — folded by default, one click to open. A run
  of twelve reads folds into a single `read · 12 files` line. `ctrl+e` expands
  everything; diffs are colored inline; rows spin while they run.
- **Bring your own models.** `/pull <model>` fetches anything from the Ollama
  registry without leaving the TUI, `f2` switches between everything
  `ollama list` reports, and a model you built from a Modelfile or imported
  from a GGUF works exactly like a registry one.
- **Build / Plan agents** — `tab` toggles them. Plan mode is read-only: edits
  and commands are refused at the tool layer, not just discouraged in the
  prompt.
- **Command palette** (`ctrl+p`) — every command, filterable.
- **Auto file discovery** — no manual `/add`. Each message is keyword-mined, the
  repo is walked (respecting `.gitignore`), files are ranked by
  filename/content matches, and the top-N are pulled into context as a folded
  `context · N files pulled in` row.
- **Tool calling** two ways:
  - native function-calling when the Ollama model supports it, or
  - a parsed text protocol: `<read path="x"/>`, `<grep pattern="x" path="x"/>`,
    `<ls path="x"/>`, `<edit path="x">...new contents...</edit>`,
    `<run>command</run>`.
- **Safe edits**: every edit renders as a unified diff and waits for `y/N`
  before being applied (unless `--yes`).
- **Git-aware**: detects the repo root on startup; offers `git init` before any
  edit or shell command when you're not in a repo.
- **Context budgeting**: estimated usage vs. the context window in the hint row,
  auto-compaction (older turns summarized) as you approach the limit.
- **Named sessions**: persisted to `~/.umbra/sessions/*.json`, resumable with
  `umbra --resume <name>`.

## Setup

1. Install Ollama and pull a model (default is the abliterate coder 7b):

   ```sh
   ollama pull huihui_ai/qwen2.5-coder-abliterate:7b
   ```

2. Install umbra:

   ```sh
   pip install -e .
   ```

   That puts `umbra` on your PATH (in Python's `Scripts` directory), so any
   terminal can launch it.

3. Optional — add it to the Start menu, so searching "umbra" launches it the
   way "opencode" does:

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\install_shortcut.ps1
   ```

   The shortcut opens a console running `umbra`, starting in
   `%USERPROFILE%\Downloads\Projects`, with the ghost icon. Pass
   `-StartIn "C:\some\path"` to start somewhere else, or `-Uninstall` to remove
   it. The icon itself is regenerated with `python tools/make_icon.py`.

## Running it

| How | What happens |
| --- | --- |
| `umbra` in a project folder | runs against that folder — the usual way |
| Start menu → "umbra" | opens a console in your projects folder; use `/cd <path>` to hop into a project |
| `umbra --cwd C:\path\to\repo` | runs against another folder without `cd`-ing |
| `python -m umbra` | same thing, without the installed command |

## Usage

```
umbra                       start (default session)
umbra --model llama3.1:8b   use a different model
umbra --host http://...     point at another Ollama server
umbra --resume nightly      resume a named session
umbra --session project-x   start/named session
umbra --yes                 auto-accept edits and shell commands
umbra --cwd ~/projects/foo  work in another directory
umbra --version             print the version
```

### In-app commands

| Command | Action |
| --- | --- |
| `/help` | list commands |
| `/clear` | clear the transcript (keep system prompt) |
| `/new <name>` | start a new named session |
| `/resume <name>` | switch to a saved session |
| `/sessions` | list saved sessions |
| `/model [name]` | switch model, or open the picker with no argument |
| `/agent` | toggle Build / Plan |
| `/compact` | compact context now |
| `/git` | re-detect git repo root |
| `/cd <path>` | change the working directory |
| `/cwd` | show working directory, repo root and branch |
| `/pull <model>` | download a model from the Ollama registry |
| `/yolo [on\|off]` | run with no confirmations, anywhere on the machine |
| `/undo` | restore the last file the model overwrote |
| `/audit` | show what has been edited and run |
| `/quit` | exit |

Keys: `tab` switch agent, `ctrl+p` command palette, `f2` model switcher,
`ctrl+e` expand/collapse the whole feed, `ctrl+n` new session, `esc` interrupt
the running turn.

Copying: drag to select and `ctrl+c`, right-click any feed row to copy it
whole, or `f12` to hand the mouse back to your terminal (then its own
selection and right-click work as usual). Clicking anywhere in the transcript
puts the cursor back in the composer.

## Total permission mode

`/yolo on` (or `umbra --yolo`, or `auto_approve = true` in the config) removes
every confirmation and lifts the git-repo requirement, so the agent edits and
runs commands anywhere on the machine unattended. It is a real handoff — an
uncensored 7B will occasionally do something wrong — so it comes with:

- every overwritten file copied to `~/.umbra/backups` first,
- `/undo` to put the last one back,
- `~/.umbra/audit.log` recording every edit and command with a timestamp,
- `esc` to interrupt a turn mid-flight.

## Config

`~/.umbra/config.toml` (all optional):

```toml
host = "http://127.0.0.1:11434"
model = "huihui_ai/qwen2.5-coder-abliterate:7b"
context_window = 32768
discovery_top_n = 6
compact_ratio = 0.7
auto_approve = false   # true = /yolo on at every launch
require_git = true
command_timeout = 120
```

## Stack

Python + [Textual](https://textual.textualize.io/),
[ollama](https://github.com/ollama/ollama-python), and the standard library
(`difflib` for diffs, `tomllib` for config). Pillow is only used by
`tools/make_icon.py`. No external services.

## Notes

- The name: *umbra* is the darkest part of a shadow — nothing here leaves the
  machine. The wordmark font covers the whole lowercase alphabet, so changing
  `NAME` in `umbra/logo.py` re-renders the logo for any name.
- The 7b default has no function-calling support, so it routes through the XML
  text protocol — tell it about the tags or it will freehand them anyway.
- Token counts are estimates (≈ 4 chars/token), a budget indicator only.
