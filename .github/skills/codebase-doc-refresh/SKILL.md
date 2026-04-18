---
name: codebase-doc-refresh
description: 'Refresh docs/codebase after architecture, module, command, convention, testing, or integration changes. Use when repo structure changed, pipeline stages moved, project guidance drifted, or codebase docs need to be updated without re-mapping the entire repo from scratch.'
argument-hint: 'Optional focus area, for example: architecture only, commands and conventions, concerns after refactor'
user-invocable: true
---

# Codebase Doc Refresh

Update the existing files under `docs/codebase/` after repository changes.

This skill is for **refreshing** the current codebase docs, not for implementing product features.
If the user asks for code changes, make those changes first and only refresh docs if requested or clearly needed.

## When To Use

Use this skill when:
- project structure changed
- a pipeline stage moved or split
- commands or entry points changed
- conventions were standardized
- known risks, debt, or testing guidance changed
- `docs/codebase/*.md` is now stale after a refactor

Do not use this skill for:
- first-time codebase mapping from scratch
- normal feature work that does not affect documentation
- speculative roadmap updates that are not reflected in the repo or confirmed by the user

## Repo-Specific Rules

- Treat `docs/codebase/` as the source of truth for AI-facing repo docs.
- Prefer updating only the affected docs instead of rewriting all seven files.
- Link to existing repo docs rather than duplicating them in other customization files.
- Ignore `GEMINI.md` and `scripts/run_optimizer_pysimplegui.py` unless the user explicitly asks to include them.
- Preserve confirmed user context already captured in `docs/codebase/CONCERNS.md`, especially:
  - Gooey replaced Streamlit for now
  - SQLite historical data is still planned but blocked by a separate architecture decision
  - the Excel loader is intentionally deferred until the user brings it back up
  - testing guidance should stay transparent and domain-relevant rather than coverage-driven

## Output Contract

Before finishing:
1. Update only the `docs/codebase/*.md` files affected by the change.
2. Keep every non-trivial claim tied to code, config, git history, or explicit user confirmation.
3. Use `[TODO]` for unknowns and `[ASK USER]` only when intent is genuinely unresolved.
4. Keep the docs aligned with `AGENTS.md` instead of contradicting it.
5. Summarize which docs changed and why.

## Procedure

### 1. Scope The Refresh

Start by identifying what changed:
- read the user's request
- check changed files in git if relevant
- read only the affected files in `docs/codebase/`
- read the corresponding code/config files that justify the update

For broad refactors, also check:
- `AGENTS.md`
- `README.md`
- `scripts/run_optimizer.py`
- `src/nba_optimizer/config.py`

### 2. Map Change Type To Docs

Use this routing table:

- `STACK.md`: dependencies, runtime, commands, env vars, packaging
- `STRUCTURE.md`: directories, entry points, module boundaries
- `ARCHITECTURE.md`: system flow, responsibilities, design risks
- `CONVENTIONS.md`: naming, imports, logging, error handling, testing norms
- `INTEGRATIONS.md`: file inputs/outputs, DraftKings workflow, external systems, data stores
- `TESTING.md`: manual verification guidance, test tooling, coverage stance
- `CONCERNS.md`: risks, debt, fragile areas, resolved user decisions

### 3. Refresh Minimally

- Edit the smallest number of docs needed.
- Preserve valid existing content.
- Do not reword stable sections just for style.
- If a user decision changes repo guidance, prefer recording it in `CONCERNS.md` and only update other docs when behavior or standards actually changed.

### 4. Validate Against The Repo

Check that updated docs still match the codebase:
- internal package imports should use relative imports
- scripts can use absolute imports from `src.nba_optimizer`
- the main pipeline remains `engine -> ranker -> exporter -> exposure_report`
- late swap remains a separate path through `late_swapper.py`
- verification guidance should not promise a formal automated test suite unless one actually exists

### 5. Report Clearly

In the final response:
- list the docs updated
- state the reason for each change briefly
- call out any remaining `[ASK USER]` items
- mention if something looks intentionally deferred rather than missing

## Practical Heuristics

- If only one or two source files changed, start from `CONVENTIONS.md` or `CONCERNS.md` before touching architecture docs.
- If entry points, directories, or orchestration changed, update `STRUCTURE.md` and `ARCHITECTURE.md` together.
- If the user clarified project direction, update `CONCERNS.md` first because it is the best place for confirmed intent and open decisions.
- If documentation drift is large, suggest a full remap after the targeted refresh is complete.
