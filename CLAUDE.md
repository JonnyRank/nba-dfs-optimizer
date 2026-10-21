@AGENTS.md

## Claude Code

### Nightly capture (O-0)

Nightly capture (O-0) is in place.
- **Folders:** each night has a slate folder under `NBA_DATA_ROOT` containing `slate.json` (locks and games), copies of the inputs, a run-record JSON next to each ranked CSV, and entry sets L0…Ln.
- **Commands:** `nba-dfs-capture finalize` searches the night's downloads and projections, assigns them to locks by modified time, checks them against the final DKEntries, and writes `slate-entries.csv`. `record` pins a file by hand.
- **Engine:** it's seeded with `--seed`.
- **Backfill:** 2026-10-20 has been backfilled.

### Cloud sessions (Claude Code on the web)

- A `SessionStart` hook (`.claude/hooks/session-start.sh`, matcher `startup|resume`) runs only when `CLAUDE_CODE_REMOTE=true` and is a no-op locally.
- In a cloud session it creates `.venv/`, runs `pip install -e .[dev]`, and prepends `.venv/bin` to `PATH`, so `python` and `pytest` are ready without a manual install.
- Local development targets Windows/PowerShell (see `AGENTS.md`); the hook and `.venv/bin` paths are POSIX-only and apply to remote sessions.
