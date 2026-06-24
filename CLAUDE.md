@AGENTS.md

## Claude Code

### Cloud sessions (Claude Code on the web)

- A `SessionStart` hook (`.claude/hooks/session-start.sh`, matcher `startup|resume`) runs only when `CLAUDE_CODE_REMOTE=true` and is a no-op locally.
- In a cloud session it creates `.venv/`, runs `pip install -e .[dev]`, and prepends `.venv/bin` to `PATH`, so `python` and `pytest` are ready without a manual install.
- Local development targets Windows/PowerShell (see `AGENTS.md`); the hook and `.venv/bin` paths are POSIX-only and apply to remote sessions.
