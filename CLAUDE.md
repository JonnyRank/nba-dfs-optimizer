@AGENTS.md

## Claude Code

### Nightly capture (O-0)

Nightly capture (O-0) is in place.
- **Folders:** each night has a slate folder under `NBA_DATA_ROOT` containing `slate.json` (locks and games), copies of the inputs, a run-record JSON next to each ranked CSV, and entry sets L0…Ln.
- **Commands:** `nba-dfs-capture finalize` searches the night's downloads and projections, assigns them to locks by modified time, checks them against the final DKEntries, and writes `slate-entries.csv`. `record` pins a file by hand.
- **Engine:** it's seeded with `--seed`.
- **Backfill:** 2026-10-20 has been backfilled.

### Stage control (O-13)

- `nba-dfs-optimizer --from {rank,assemble,export} [--to …]` reruns part of the pipeline on tonight's slate folder.
- Settings carry forward. Typed overrides last until the export changes that player. Clear them with `--clear-overrides`, `--clear-caps` or `--reset-settings`.
- `--proj/--own` overrides; assemble is a rank-sum ILP with `--max/--min/--max-all`, writing `assembled-lineups-*.csv/.json`.
- Export takes the assembly and its entry set records `assembly_id`.
- The Gooey GUI shares the same argument definitions.
- On a finished slate, `--from rank` uses the parent run's projections and a full run uses the folder's newest L0 copy; `--no-slate-folder` keeps an experiment out of the night's capture.

### Uniqueness at assemble (O-14)

- The engine writes every generated lineup. `-u/--min_unique` is applied at assemble by walking the ranked pool: of two lineups sharing more than 8−u players, the better-ranked stays. The O-13 caps ILP then picks from the survivors; with no caps it takes the top N without a solver.
- The solver has a 10 s limit and reports `proven_optimal`. `-u` carries forward like the caps; the GUI box is pre-filled with 1.

### Cloud sessions (Claude Code on the web)

- A `SessionStart` hook (`.claude/hooks/session-start.sh`, matcher `startup|resume`) runs only when `CLAUDE_CODE_REMOTE=true` and is a no-op locally.
- In a cloud session it creates `.venv/`, runs `pip install -e .[dev]`, and prepends `.venv/bin` to `PATH`, so `python` and `pytest` are ready without a manual install.
- Local development targets Windows/PowerShell (see `AGENTS.md`); the hook and `.venv/bin` paths are POSIX-only and apply to remote sessions.
