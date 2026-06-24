# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

All project conventions, architecture, build/run commands, pitfalls, and testing
guidance live in the shared agent guide. Read it first:

@AGENTS.md

## Claude Code Specifics

The notes below apply only to Claude Code and supplement (do not replace) `AGENTS.md`.

### Cloud sessions (Claude Code on the web)

This repo ships a `SessionStart` hook at `.claude/hooks/session-start.sh`, wired up in
`.claude/settings.json` for the `startup` and `resume` matchers. It bootstraps the Python
environment so tests and linters work in remote sessions:

- It runs **only** when `CLAUDE_CODE_REMOTE=true`; on a local developer machine it exits
  immediately and changes nothing.
- In a cloud session it creates `.venv/` (once, reused on resume), installs the package with
  dev extras (`pip install -e .[dev]`), and prepends `.venv/bin` to `PATH` via
  `$CLAUDE_ENV_FILE` so `python` and `pytest` resolve to the venv on every startup and resume.

Because of this, in a cloud session you can run `python -m pytest -q` directly without a
manual install step. If dependencies seem missing, confirm the hook ran (check for `.venv/`)
rather than re-installing by hand. See https://code.claude.com/docs/en/claude-code-on-the-web
for how remote environments, triggers, and SessionStart hooks work.

> Note: `AGENTS.md` states the project targets Windows/PowerShell for local development.
> Cloud sessions run on Linux, so the bootstrap hook and `.venv/bin` paths above are
> POSIX-shell specific and apply to the remote environment only.
