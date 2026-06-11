# Plan 003: Replace latest-file pipeline handoff with explicit stage artifacts

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat d6cbd5f..HEAD -- src/nba_optimizer/orchestrator.py src/nba_optimizer/engine.py src/nba_optimizer/ranker.py src/nba_optimizer/exporter.py src/nba_optimizer/exposure_report.py src/nba_optimizer/utils.py src/nba_optimizer/config.py README.md docs/codebase/ARCHITECTURE.md docs/codebase/CONCERNS.md BACKLOG.md`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/001-establish-verification-baseline.md`
- **Category**: bug
- **Planned at**: commit `d6cbd5f`, 2026-06-11
- **Issue**: https://github.com/JonnyRank/nba-dfs-optimizer/issues/42

## Why this matters

The pipeline currently links stages by asking each module for the newest matching file on disk. That works when every run completes cleanly, but it fails badly after interruptions or partial outputs: a stale lineup pool can be ranked, a stale ranked file can be exported, and the user gets a file that appears current but is actually assembled from mixed runs. This plan makes stage handoff explicit so one pipeline execution only consumes artifacts produced by that same execution.

## Current state

Relevant files and their current roles:

- `src/nba_optimizer/orchestrator.py` — runs engine, ranker, exporter, and exposure report in order.
- `src/nba_optimizer/engine.py` — writes `lineup-pool-{timestamp}.csv` but returns no path to the caller.
- `src/nba_optimizer/ranker.py` — resolves the latest lineup pool and latest projections from disk.
- `src/nba_optimizer/exporter.py` — resolves the latest ranked file from disk.
- `src/nba_optimizer/exposure_report.py` — independently resolves the latest export file.
- `src/nba_optimizer/utils.py` — currently only exposes generic latest-file lookup, not run-scoped artifact tracking.

Current-state excerpts:

- `src/nba_optimizer/orchestrator.py:20-41`

  ```py
  engine.run(config, ...)
  ranker.run(config, ...)
  exporter.run(config)
  exposure_report.run(config, top_x=args.top_x)
  ```

- `src/nba_optimizer/engine.py:253-373`

  ```py
  projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv")
  ...
  output_file = os.path.join(cfg.lineup_pool_dir, f"lineup-pool-{timestamp}.csv")
  out_df.to_csv(output_file, index=False)
  ```

- `src/nba_optimizer/ranker.py:88-91`

  ```py
  lineup_file = get_latest_file(cfg.lineup_pool_dir, "lineup-pool-*.csv")
  projs_file = get_latest_file(cfg.projs_dir, "NBA-Projs-*.csv")
  ```

- `src/nba_optimizer/exporter.py:28`

  ```py
  ranked_file = get_latest_file(cfg.ranked_lineup_dir, "ranked-lineups-*.csv")
  ```

- `src/nba_optimizer/exposure_report.py:31-42`

  ```py
  candidates = []
  for pattern in patterns:
      try:
          candidates.append(get_latest_file(cfg.output_dir, pattern, use_mtime=True))
  ```

Repo conventions to follow:

- Keep module responsibilities separated: engine generates, ranker ranks, exporter maps into DK CSV, exposure report reports. Do not move ranking/export logic into the engine.
- Preserve `Config` injection and relative imports inside `src/nba_optimizer/`.
- Maintain the project’s simple `print()`-based status output.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Imports after refactor | `python -c "from nba_optimizer import orchestrator, engine, ranker, exporter, exposure_report"` | exit 0 |
| Focused tests from plan 001 | `python -m pytest -q` | exit 0 |
| Manual artifact contract smoke | `python -c "from nba_optimizer.orchestrator import run_pipeline; print('import ok')"` | prints `import ok` |

## Scope

**In scope**:

- `src/nba_optimizer/orchestrator.py`
- `src/nba_optimizer/engine.py`
- `src/nba_optimizer/ranker.py`
- `src/nba_optimizer/exporter.py`
- `src/nba_optimizer/exposure_report.py`
- `src/nba_optimizer/utils.py`
- `src/nba_optimizer/config.py` (only if a small artifact carrier type belongs here)
- `README.md`
- `docs/codebase/ARCHITECTURE.md`
- `docs/codebase/CONCERNS.md`
- `BACKLOG.md` (optional status update only)

**Out of scope**:

- changing artifact file naming conventions beyond what is required to encode explicit handoff
- GUI-specific stop-button behavior
- late-swap pipeline redesign
- broader filesystem abstraction or database persistence

## Git workflow

- Branch: `advisor/003-explicit-pipeline-artifacts`
- Commit using the repo’s conventional style, for example: `feat: pass explicit stage artifacts through orchestrator`
- Do NOT push or open a PR unless the operator instructs it.

## Steps

### Step 1: Choose a narrow artifact contract

Design a minimal artifact handoff shape that can be passed between stages without changing module ownership. The most likely options are:

- returning output file paths from each `run()` function, or
- returning a tiny dataclass / dict of stage outputs from each stage and threading it through the orchestrator.

Prefer the simplest contract that lets the orchestrator pass the exact lineup-pool file into the ranker, the exact ranked file into the exporter, and the exact export file into the exposure report. Avoid a large “pipeline context” abstraction unless the small return-value approach clearly fails.

**Verify**: `python -c "from nba_optimizer import orchestrator, engine, ranker, exporter, exposure_report"` → exit 0

### Step 2: Refactor stage entry points to accept explicit inputs

Update the stage modules so their `run()` functions can accept explicit upstream artifact paths. Preserve current standalone usability by letting `main()` continue to default to latest-file resolution when the user runs a stage in isolation.

Concrete target shape:

- `engine.run(...)` returns the written lineup-pool file path
- `ranker.run(..., lineup_file=None, projs_file=None)` accepts explicit inputs and returns the ranked file path
- `exporter.run(..., ranked_file=None)` accepts an explicit ranked artifact and returns the export file path
- `exposure_report.run(..., entries_file=None)` already supports an explicit file path; keep that path first-class

**Verify**: `python -m pytest -q` → exit 0

### Step 3: Thread the explicit artifacts through orchestrator.py

Update `run_pipeline()` so the default full pipeline never uses latest-file lookup between stages. The orchestrator should capture the output of `engine.run()`, pass it into `ranker.run()`, capture the output of `ranker.run()`, pass it into `exporter.run()`, and finally pass the export artifact path into `exposure_report.run()`.

Preserve the late-swap path unless a tiny adjustment is required to keep exposure reporting explicit there too.

**Verify**: `python -c "from nba_optimizer.orchestrator import run_pipeline; print('import ok')"` → prints `import ok`

### Step 4: Keep standalone modules backward-compatible

Ensure the standalone `main()` functions in `ranker.py`, `exporter.py`, and `exposure_report.py` still work without orchestrator-provided paths by falling back to the existing `get_latest_file()` behavior when explicit paths are absent.

This preserves the current user workflow while fixing the orchestrated path.

**Verify**: `python -c "from nba_optimizer import ranker, exporter, exposure_report; print('standalone imports ok')"` → prints `standalone imports ok`

### Step 5: Update docs to describe the new contract

Revise `README.md`, `docs/codebase/ARCHITECTURE.md`, and `docs/codebase/CONCERNS.md` so they describe explicit stage handoff for orchestrated runs and latest-file fallback only for standalone module usage.

If you update `BACKLOG.md`, mark the run-ID / stale-file design task in a way that reflects what was actually implemented.

**Verify**: `python -m pytest -q` → exit 0

## Test plan

- Re-run the baseline tests from plan 001.
- Add or extend tests, if plan 001 created the infrastructure, to cover:
  - `ranker.run()` honoring an explicit `lineup_file`
  - `exporter.run()` honoring an explicit `ranked_file`
  - `exposure_report._resolve_entries_file()` still honoring explicit `entries_file`
- If lightweight filesystem tests are practical, use temporary directories to prove the orchestrated path no longer depends on “latest file” order.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `python -m pytest -q` exits 0
- [ ] `python -c "from nba_optimizer import orchestrator, engine, ranker, exporter, exposure_report"` exits 0
- [ ] The full orchestrator path passes explicit artifact paths between stages instead of resolving newest files from disk
- [ ] Standalone module entry points still support latest-file fallback when explicit inputs are absent
- [ ] Docs describe the new orchestrated-vs-standalone behavior accurately
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- plan 001 has not landed and there is still no automated regression check
- the late-swap path turns out to require a broader contract redesign than the standard pipeline
- the cleanest solution would require changing artifact naming across the whole repo rather than adding explicit parameters/returns
- any stage currently relied on side effects from latest-file discovery that are not documented here

## Maintenance notes

- Reviewers should verify that module boundaries stayed intact. Passing file paths is fine; moving business logic across stages is not.
- Future stages like `simulator.py` should follow the same pattern: explicit artifact input in orchestrated mode, latest-file fallback only for standalone use.
- Once this lands, stale-file pickup risk should move from “known architecture concern” to a smaller residual risk limited to standalone/manual invocations.
